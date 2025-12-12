import { Injectable, OnDestroy } from '@angular/core';
import { AgentService } from './agent.service';

@Injectable({
  providedIn: 'root'
})
export class RecordingService implements OnDestroy {
  private isRecording = false;
  private socket: WebSocket | null = null;
  private eventListeners: any[] = [];

  constructor(private agentService: AgentService) {}

  setSocket(ws: WebSocket) {
    this.socket = ws;
  }

  startRecording() {
    this.isRecording = true;
    this.attachListeners();
    console.log('[Recorder] Started');
  }

  stopRecording() {
    this.isRecording = false;
    this.removeListeners();
    console.log('[Recorder] Stopped');
  }

  private attachListeners() {
    this.removeListeners(); 

    // 1. Click Listener (Buttons, Links)
    const clickHandler = (e: MouseEvent) => {
      if (!this.isRecording) return;
      const target = e.target as HTMLElement;
      
      if (target.closest('.agent-chat-container')) return;
      
      // Ignore inputs/selects in click handler, they have their own events
      if (['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;

      this.recordAction('click', target);
    };

    // 2. Change Listener (Select, Checkbox, Radio, Finalized Input)
    const changeHandler = (e: Event) => {
      if (!this.isRecording) return;
      const target = e.target as HTMLElement;

      // A. Handle Select
      if (target.tagName === 'SELECT') {
        const selectEl = target as HTMLSelectElement;
        const selectedOption = selectEl.options[selectEl.selectedIndex];
        // Record the visible text ("Three")
        this.recordAction('select', target, selectedOption.text.trim());
      }
      
      // B. Handle Text Input (on change/blur)
      else if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
          const inputEl = target as HTMLInputElement;
          // Ignore checkbox/radio here if you prefer clicks, but 'change' is safer for state
          if (inputEl.type !== 'checkbox' && inputEl.type !== 'radio') {
             this.recordAction('type', target, inputEl.value);
          }
      }
    };

    document.addEventListener('click', clickHandler, true);
    document.addEventListener('change', changeHandler, true); 

    this.eventListeners.push(
      { type: 'click', fn: clickHandler },
      { type: 'change', fn: changeHandler }
    );
  }

  private removeListeners() {
    this.eventListeners.forEach(l => document.removeEventListener(l.type, l.fn, true));
    this.eventListeners = [];
  }

  // 🔥 Async: Capture Full Context + Visual Crop
  private async recordAction(type: string, el: HTMLElement, value: string = '') {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return;

    const desc = this.agentService.getElementDescription(el);
    
    // Parallel Execution for performance
    const [context, cropBase64] = await Promise.all([
        this.agentService.captureContext(),
        this.agentService.captureElementCrop(el)
    ]);
    
    const payload = {
      type: 'record_event',
      action: {
        type: type, 
        value: value
      },
      element_desc: desc,
      timestamp: Date.now(),
      
      // Full Data for SFT
      dom: context.dom,
      screenshot: context.screenshot, // Full Screen
      visual_crop: cropBase64         // Visual Anchor
    };

    console.log(`[Recorder] Sending: ${type} on "${desc}" (Val: ${value}) | Full+Crop Captured`);
    this.socket.send(JSON.stringify(payload));
  }

  ngOnDestroy() {
    this.removeListeners();
  }
}