import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { DragDropModule } from '@angular/cdk/drag-drop';
import { AgentService } from '../../services/agent.service';
import { RecordingService } from '../../services/recording.service';

interface ChatMessage {
  id: string;
  type: 'user' | 'agent' | 'system';
  text: string;
  feedback?: 'good' | 'bad' | null;
  actionData?: any;
}

@Component({
  selector: 'vlab-agent-chat',
  standalone: true,
  imports: [CommonModule, FormsModule, DragDropModule],
  templateUrl: './agent-chat.component.html',
  styleUrl: './agent-chat.component.scss'
})
export class AgentChatComponent implements OnInit, OnDestroy {
  socket: WebSocket | null = null;
  inputText = '';
  
  messages: ChatMessage[] = [
    { id: 'init', type: 'agent', text: '👋 AI Assistant Ready.\n\n• Chat Mode: Ask about page\n• Task Mode: Execute instructions' }
  ];

  // State flags
  isRecording = false;
  isConnected = false;
  autoRunning = false;
  isMinimized = false;
  
  // Review Mode State
  isReviewing = false;
  reviewSteps: any[] = [];
  reviewTaskName = '';

  // UI Status
  connectionStatus = 'Connecting...';
  currentMode: 'chat' | 'task' = 'chat';
  currentTask = '';
  stepCount = 0;

  private reconnectTimer: any; 
  private isComponentAlive = true;

  constructor(
    private agentService: AgentService,
    private recordingService: RecordingService
  ) {}

  ngOnInit() { this.connectWebSocket(); }

  // --- WebSocket Connection ---
  connectWebSocket() {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) return;

    this.connectionStatus = 'Connecting...';
    
    try {
        this.socket = new WebSocket('ws://localhost:8000/ws');

        this.socket.onopen = () => {
          this.isConnected = true;
          if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
          
          this.connectionStatus = '🟢 Connected';
          
          if (this.socket) this.recordingService.setSocket(this.socket);
        };

        this.socket.onmessage = (event) => this.handleIncomingMessage(event.data);

        this.socket.onclose = () => {
          this.isConnected = false;
          this.autoRunning = false; 
          
          if (this.isComponentAlive) {
              this.connectionStatus = '🔴 Disconnected';
              console.warn('[Agent] Connection lost. Retrying in 3s...');
              
              if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
              this.reconnectTimer = setTimeout(() => {
                  this.connectWebSocket();
              }, 3000);
          }
        };

        this.socket.onerror = (err) => {
            console.error('[Agent] WebSocket Error:', err);
            this.socket?.close();
        };

    } catch (e) {
        console.error("[Agent] Connection setup failed", e);
        if (this.isComponentAlive) {
            this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 3000);
        }
    }
  }

  // --- Message Handling ---
  handleIncomingMessage(jsonStr: string) {
    try {
      const cmd = JSON.parse(jsonStr);
      const msgId = Date.now().toString();

      // 1. Handle Preview Data (Review Mode)
      if (cmd.action === 'preview_data') {
          this.reviewSteps = cmd.data;
          this.isReviewing = true;
          return;
      }

      // 2. Handle Text Messages & Completion Signals
      // 🔥 FIX: Accept 'return', 'finish', 'done' as valid completion signals from LLM
      if (['message', 'return', 'finish', 'done'].includes(cmd.action)) {
        const text = cmd.value || 'Task Completed';
        this.messages.push({ id: msgId, type: 'agent', text: text });
        
        if (this.autoRunning) {
          this.stopAutoRun('Task Completed by AI');
        }
      } 
      // 3. Handle Actions
      else if (['click', 'type', 'select'].includes(cmd.action)) {
        const result = this.agentService.executeCommand(cmd.action, cmd.id, cmd.value);
        
        this.messages.push({
          id: msgId,
          type: 'agent',
          text: `Step ${this.stepCount}: ${result}`,
          actionData: cmd, 
          feedback: null
        });

        if (result.startsWith('❌')) {
          this.messages.push({ id: msgId + '_fail', type: 'system', text: result });
          this.sendFeedback(msgId, 'bad', cmd); 
          this.stopAutoRun('Execution Error');
        } else {
          // Auto-Loop
          if (this.autoRunning) {
            this.triggerNextStep();
          }
        }
      }
      this.scrollToBottom();
    } catch (e) {
      console.error(e);
    }
  }

  // --- Auto-Loop ---
  triggerNextStep() {
    this.stepCount++;
    if (this.stepCount > 20) {
      this.stopAutoRun('Max step limit reached');
      return;
    }
    setTimeout(() => {
      if (!this.autoRunning) return;
      this.sendToBackend(this.currentTask, false); 
    }, 2500);
  }

  // --- Send Message ---
  send() {
    if (!this.inputText.trim()) return;
    const cmd = this.inputText.trim();
    this.messages.push({ id: Date.now().toString(), type: 'user', text: cmd });
    this.inputText = '';

    // Local Debug Scan
    if (cmd.toLowerCase() === 'scan' && this.currentMode === 'task') {
      const domSnapshot = this.agentService.scanPage();
      console.log(domSnapshot);
      this.messages.push({
        id: Date.now().toString() + '_scan',
        type: 'system',
        text: `📄 Scan Complete (${domSnapshot.split('\n').length} elements)\n(Check console)`
      });
      return;
    }

    if (!this.isConnected) {
      this.messages.push({ id: 'err', type: 'system', text: 'Not Connected' });
      return;
    }

    if (this.currentMode === 'task') {
      this.currentTask = cmd;
      this.autoRunning = true;
      this.stepCount = 1;
      this.messages.push({ id: 'sys_run', type: 'system', text: '🚀 Task Started...' });
      this.sendToBackend(this.currentTask, true); 
    } else {
      this.sendToBackend(cmd, true);
    }
  }

  sendToBackend(task: string, isNewTask: boolean) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        this.stopAutoRun("Connection lost");
        return;
    }
    const dom = this.agentService.scanPage();
    this.socket.send(JSON.stringify({
      instruction: task,
      dom: dom,
      mode: this.currentMode,
      is_new_task: isNewTask
    }));
    this.scrollToBottom();
  }

  // --- Recording & Review ---
  toggleRecording() {
    if (this.autoRunning) this.stopAutoRun('Switching to record');

    this.isRecording = !this.isRecording;
    if (this.isRecording) {
      this.agentService.scanPage(); 
      this.recordingService.startRecording();
      this.messages.push({ id: 'rec_start', type: 'system', text: '🔴 Recording started...' });
    } else {
      this.recordingService.stopRecording();
      const taskName = window.prompt("Recording stopped! Please name this task:");
      
      if (taskName) {
        this.reviewTaskName = taskName;
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
             this.socket.send(JSON.stringify({ type: 'request_preview' }));
        }
      } else {
        this.messages.push({ id: 'rec_cancel', type: 'system', text: '⚠️ Unnamed, discarded' });
      }
    }
  }

  // Review Actions
  removeStep(index: number) {
      this.reviewSteps.splice(index, 1);
  }

  confirmSave() {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ 
            type: 'save_demo', 
            name: this.reviewTaskName,
            steps: this.reviewSteps 
        }));
        this.messages.push({ id: 'rec_end', type: 'system', text: `💾 Demo "${this.reviewTaskName}" Saved.` });
      }
      this.isReviewing = false;
      this.reviewSteps = [];
  }

  cancelSave() {
      this.isReviewing = false;
      this.reviewSteps = [];
      this.messages.push({ id: 'rec_cancel', type: 'system', text: '⚠️ Save cancelled.' });
  }

  // --- Helpers ---
  setMode(mode: 'chat' | 'task') {
    this.currentMode = mode;
    this.messages.push({
      id: Date.now().toString(),
      type: 'system',
      text: mode === 'chat' ? '💬 Chat Mode' : '⚡ Task Mode'
    });
  }

  toggleMinimize(e: Event) {
    e.stopPropagation();
    this.isMinimized = !this.isMinimized;
  }

  stopAutoRun(reason: string = '') {
    if (this.autoRunning) {
      this.autoRunning = false;
      this.messages.push({ id: 'sys_stop', type: 'system', text: `⏹️ Stopped: ${reason}` });
    }
  }

  sendFeedback(msgId: string, rating: 'good' | 'bad', actionData: any) {
    const msg = this.messages.find(m => m.id === msgId);
    if (msg) msg.feedback = rating;

    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({
          type: 'feedback',
          rating: rating === 'good' ? 1 : -1,
          action: actionData
        }));
    }
  }

  scrollToBottom() {
    setTimeout(() => {
      const el = document.querySelector('.messages');
      if (el) el.scrollTop = el.scrollHeight;
    }, 100);
  }

  ngOnDestroy() {
    this.isComponentAlive = false; 
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    
    if (this.socket) {
        this.socket.close();
    }
    this.recordingService.stopRecording();
  }
}