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

  isRecording = false;
  isConnected = false;
  autoRunning = false;
  isMinimized = false;
  
  isReviewing = false;
  reviewSteps: any[] = [];
  reviewTaskName = '';

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

  connectWebSocket() {
    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) return;

    this.connectionStatus = 'Connecting...';
    
    try {
        const ws = new WebSocket('ws://localhost:8000/ws');
        this.socket = ws;

        ws.onopen = () => {
          this.isConnected = true;
          if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
          
          this.connectionStatus = '🟢 Connected';
          
          this.recordingService.setSocket(ws);

          const routeInfo = this.agentService.getRouteInfo();
          ws.send(JSON.stringify({
            type: 'sitemap_init',
            routes: routeInfo.routes,
            version: routeInfo.version_hash
          }));
          console.log('[Agent] Sitemap Skeleton sent.');
        };

        ws.onmessage = (event) => this.handleIncomingMessage(event.data);

        ws.onclose = () => {
          this.isConnected = false;
          this.autoRunning = false; 
          this.socket = null;
          
          if (this.isComponentAlive) {
              this.connectionStatus = '🔴 Disconnected';
              console.warn('[Agent] Connection lost. Retrying in 3s...');
              
              if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
              this.reconnectTimer = setTimeout(() => {
                  this.connectWebSocket();
              }, 3000);
          }
        };

        ws.onerror = (err) => {
            console.error('[Agent] WebSocket Error:', err);
            ws.close();
        };

    } catch (e) {
        console.error("[Agent] Connection setup failed", e);
        if (this.isComponentAlive) {
            this.reconnectTimer = setTimeout(() => this.connectWebSocket(), 3000);
        }
    }
  }

  handleIncomingMessage(jsonStr: string) {
    try {
      const cmd = JSON.parse(jsonStr);
      const msgId = Date.now().toString();

      if (cmd.action === 'preview_data') {
          this.reviewSteps = cmd.data;
          this.isReviewing = true;
          return;
      }

      // Handle completion AND failure signals
      if (['message', 'return', 'finish', 'done', 'error'].includes(cmd.action)) {
        const text = cmd.value || 'Task Completed';
        
        this.messages.push({ 
            id: msgId, 
            type: cmd.action === 'error' ? 'system' : 'agent', 
            text: text 
        });
        
        // Stop Loop Condition
        if (this.autoRunning) {
            const lowerText = text.toLowerCase();
            if (
                lowerText.includes('task completed') || 
                lowerText.includes('task failed') || 
                lowerText.includes('error') ||
                cmd.action === 'finish' ||
                cmd.action === 'error'
            ) {
                this.stopAutoRun(text);
            }
        }
      } 
      else if (['click', 'type', 'select'].includes(cmd.action)) {
          const result = this.agentService.executeCommand(cmd.action, cmd.id, cmd.value);
          
          this.messages.push({
            id: msgId,
            type: 'agent',
            text: `Step ${this.stepCount}: ${result}`,
            actionData: cmd, 
            feedback: null
          });

          // 🔥🔥 RUNTIME GUARD: Check for Execution Errors 🔥🔥
          if (result.startsWith('❌')) {
            this.messages.push({ id: msgId + '_fail', type: 'system', text: result });
            
            if (this.autoRunning) {
                console.warn('[Agent] Runtime Error, requesting correction from backend...');
                
                // 🔥🔥 FIX: Re-capture context IMMEDIATELY for the retry
                // This ensures the AI sees the EXACT current state (fixes offset issues)
                this.agentService.captureContext().then(contextData => {
                    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
                        this.socket.send(JSON.stringify({
                            type: 'client_error',
                            error: result,
                            // Send fresh data
                            dom: contextData.dom,
                            screenshot: contextData.screenshot,
                            elements_meta: contextData.elements_meta
                        }));
                    }
                });
            } else {
                this.stopAutoRun('Execution Error');
            }
          } else {
            // Success case
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

  triggerNextStep() {
    this.stepCount++;
    if (this.stepCount > 30) {
      this.stopAutoRun('Max step limit reached');
      return;
    }
    setTimeout(() => {
      if (!this.autoRunning) return;
      this.sendToBackend(this.currentTask, false); 
    }, 2500);
  }

  send() {
    if (!this.inputText.trim()) return;
    const cmd = this.inputText.trim();
    this.messages.push({ id: Date.now().toString(), type: 'user', text: cmd });
    this.inputText = '';

    if (cmd.toLowerCase() === 'scan' && this.currentMode === 'task') {
      const domSnapshot = this.agentService.scanPage();
      console.log(domSnapshot);
      this.messages.push({
        id: Date.now().toString() + '_scan',
        type: 'system',
        text: `📄 Scan Complete (${domSnapshot.split('\n').length} elements)`
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

  async sendToBackend(task: string, isNewTask: boolean) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
        this.stopAutoRun("Connection lost");
        return;
    }
    
    const contextData = await this.agentService.captureContext();
    const currentUrl = window.location.hash || window.location.pathname; 
    const title = document.title; 

    this.socket.send(JSON.stringify({
      instruction: task,
      dom: contextData.dom,
      page_structure: contextData.page_structure,
      screenshot: contextData.screenshot,
      elements_meta: contextData.elements_meta,
      mode: this.currentMode,
      is_new_task: isNewTask,
      url: currentUrl, 
      title: title 
    }));
    
    this.scrollToBottom();
  }

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

  removeStep(index: number) { this.reviewSteps.splice(index, 1); }

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

  setMode(mode: 'chat' | 'task') {
    this.currentMode = mode;
    this.messages.push({ id: Date.now().toString(), type: 'system', text: mode === 'chat' ? '💬 Chat Mode' : '⚡ Task Mode' });
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
    if (this.socket) this.socket.close();
    this.recordingService.stopRecording();
  }
}