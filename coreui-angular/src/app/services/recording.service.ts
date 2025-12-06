import { Injectable } from '@angular/core';
import { AgentService } from './agent.service';

@Injectable({
  providedIn: 'root'
})
export class RecordingService {
  private isRecording = false;
  private socket: WebSocket | null = null;
  
  // Store references to bound listeners for removal
  private clickListener: any;
  private inputListener: any;

  constructor(private agentService: AgentService) {
    // Pre-bind context
    this.clickListener = this.handleClick.bind(this);
    this.inputListener = this.handleInput.bind(this);
  }

  public setSocket(ws: WebSocket) {
    this.socket = ws;
  }

  /**
   * Start recording
   * Use capture phase (true) to catch events before business logic stops propagation
   */
  public startRecording() {
    if (this.isRecording) return;
    this.isRecording = true;
    console.log('TZ 🔴 Recording started...');
    
    document.addEventListener('click', this.clickListener, true);
    document.addEventListener('change', this.inputListener, true);
  }

  /**
   * Stop recording
   */
  public stopRecording() {
    this.isRecording = false;
    console.log('TZ ⏹️ Recording stopped');
    
    document.removeEventListener('click', this.clickListener, true);
    document.removeEventListener('change', this.inputListener, true);
  }

  // --- Event Handlers ---

  private handleClick(event: MouseEvent) {
    const target = event.target as HTMLElement;
    // Ignore clicks inside the Agent Chat window itself
    if (target.closest('.agent-chat-container')) return;

    this.processEvent('click', target);
  }

  private handleInput(event: Event) {
    const target = event.target as HTMLElement;
    // Ignore input inside the Agent Chat window itself
    if (target.closest('.agent-chat-container')) return;
    
    let value = '';
    // Get value from Input, Textarea, or Select
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) {
        value = target.value;
    }
    this.processEvent('type', target, value);
  }

  /**
   * Core Logic: Convert DOM events into semantic Agent records
   */
  private processEvent(actionType: string, el: HTMLElement, value: string = '') {
    // 1. Ensure ID exists (Assign temporary ID if the page hasn't been scanned yet)
    let agentId = el.getAttribute('data-agent-id');
    if (!agentId) {
        agentId = `REC-${Date.now()}`;
        el.setAttribute('data-agent-id', agentId);
    }

    // 2. 🔥 Critical: Get "Semantic Description" of the element
    // Call the public method from AgentService (v6) to ensure the recorded data 
    // includes hierarchy context (e.g., [Card > Header] Button)
    const desc = this.agentService.getElementDescription(el);

    const recordData = {
        type: 'record_event',
        timestamp: Date.now(),
        url: window.location.href,
        action: {
            type: actionType,
            target_id: agentId, 
            value: value
        },
        element_desc: desc  // This is the training material for DeepSeek
    };

    // 3. Send to Python Backend for storage
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify(recordData));
    }
  }
}