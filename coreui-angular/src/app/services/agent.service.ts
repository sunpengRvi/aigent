import { Injectable } from '@angular/core';
import { computeAccessibleName } from 'dom-accessibility-api';

@Injectable({
  providedIn: 'root'
})
export class AgentService {
  private uniqueIdCounter = 0;

  constructor() {}

  /**
   * 👁️ [Eyes] Scan Page
   */
  scanPage(): string {
    const report: string[] = [];
    this.uniqueIdCounter = 1;

    const elements = document.querySelectorAll('*'); 

    elements.forEach((node) => {
      const el = node as HTMLElement;
      
      // 1. Basic Filtering
      if (!this.isVisible(el)) return;
      if (el.closest('.agent-chat-container')) return;
      
      // 2. Interactivity Check
      const tagName = el.tagName.toLowerCase();
      const interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'details'];
      const interactiveRoles = ['button', 'link', 'checkbox', 'radio', 'textbox', 'listbox', 'combobox', 'menuitem', 'tab'];
      const role = el.getAttribute('role');

      const isInteractive = interactiveTags.includes(tagName) || (role && interactiveRoles.includes(role));
      if (!isInteractive) return;

      // 3. Tagging
      const agentId = this.uniqueIdCounter++;
      el.setAttribute('data-agent-id', agentId.toString());

      // 4. Feature Extraction
      const type = el.getAttribute('type') || '';
      const href = el.getAttribute('href') || '';
      const name = el.getAttribute('name') || '';
      const placeholder = el.getAttribute('placeholder') || '';
      const testId = el.getAttribute('data-testid') || el.id || '';
      
      let attrParts = [];
      if (type) attrParts.push(`type="${type}"`);
      if (href && href !== '#' && !href.startsWith('javascript')) {
          attrParts.push(`href="${href}"`);
      }
      if (name) attrParts.push(`name="${name}"`);
      if (testId) attrParts.push(`id="${testId}"`);
      if (placeholder) attrParts.push(`placeholder="${placeholder}"`);
      
      const attrsStr = attrParts.length > 0 ? ' ' + attrParts.join(' ') : '';

      // 5. Semantic Description + Structure
      let finalDesc = this.getElementDescription(el);

      // 6. 🔥 Active State Detection (Critical for navigation logic)
      if (el.classList.contains('active') || el.getAttribute('aria-current') === 'page') {
          finalDesc += ' [Active]';
      }

      // 7. Input State Info
      let stateInfo = '';
      if (tagName === 'input') {
        if (type === 'checkbox' || type === 'radio') {
          stateInfo = `[Checked: ${(el as HTMLInputElement).checked}]`;
        } else {
          stateInfo = `[Value: "${(el as HTMLInputElement).value}"]`;
        }
      } else if (tagName === 'select') {
        const select = el as HTMLSelectElement;
        const selectedOption = select.options[select.selectedIndex];
        stateInfo = `[Selected: "${selectedOption ? selectedOption.text.trim() : select.value}"]`;
      }

      report.push(`[${agentId}] <${tagName}${attrsStr}> "${finalDesc}" ${stateInfo}`);
    });

    return report.join('\n');
  }

  /**
   * Get Semantic Description + Spatial Context
   */
  public getElementDescription(el: HTMLElement): string {
      let accName = computeAccessibleName(el);
      if (!accName && el.innerText) {
          accName = this.cleanText(el.innerText);
      }
      
      const hierarchy = this.getHierarchyPath(el);
      const structure = this.getStructuralContext(el);

      let desc = accName;
      
      if (hierarchy) {
         if (!accName.includes(hierarchy)) {
             desc = `${hierarchy} > ${accName}`;
         }
      }
      
      if (structure) {
          desc = `[${structure}] ${desc}`;
      }
      
      if (!desc || desc.trim() === '') desc = "Unnamed Element";
      if (desc.length > 150) desc = desc.substring(0, 150) + '...';
      
      return desc;
  }

  private getStructuralContext(el: HTMLElement): string {
      let parent = el.parentElement;
      let depth = 0;
      
      while (parent && depth < 10) {
          const cls = parent.classList;
          const id = parent.id || '';
          
          if (cls.contains('sidebar') || cls.contains('c-sidebar') || id.includes('sidebar')) return 'Sidebar';
          if (cls.contains('breadcrumb') || cls.contains('c-breadcrumb')) return 'Breadcrumb';
          if (cls.contains('header') || cls.contains('c-header') || cls.contains('navbar')) return 'Header';
          if (cls.contains('footer') || cls.contains('c-footer')) return 'Footer';
          
          parent = parent.parentElement;
          depth++;
      }
      return '';
  }

  private getHierarchyPath(el: HTMLElement): string {
    const paths: string[] = [];
    let parent = el.parentElement;
    let depth = 0;

    while (parent && depth < 5) {
      const classList = parent.classList;
      const tagName = parent.tagName;
      let foundTitle = '';

      if (classList.contains('card') || classList.contains('c-card') || classList.contains('card-body')) {
        const card = classList.contains('card-body') ? parent.parentElement : parent;
        const header = card?.querySelector('.card-header, .c-card-header');
        if (header) foundTitle = this.cleanText(header.textContent || '');
      }
      else if (classList.contains('form-group') || classList.contains('mb-3')) {
        const groupLabel = parent.querySelector('label, h6');
        if (groupLabel) {
            const forAttr = groupLabel.getAttribute('for');
            if (!forAttr || forAttr !== el.id) foundTitle = this.cleanText(groupLabel.textContent || '');
        }
      }
      
      if (foundTitle && foundTitle.length > 0 && foundTitle.length < 40 && !paths.includes(foundTitle)) {
        paths.unshift(foundTitle);
      }
      parent = parent.parentElement;
      depth++;
    }
    return paths.join(' > ');
  }

  executeCommand(action: string, id: string, value: string = ''): string {
    const el = document.querySelector(`[data-agent-id="${id}"]`) as HTMLElement;
    if (!el) return `❌ ID [${id}] not found`;

    this.highlightElement(el);
    const elementDesc = this.getElementDescription(el); 
    const shortDesc = elementDesc.length > 50 ? elementDesc.substring(0, 50) + '...' : elementDesc;

    try {
      switch (action) {
        case 'click':
          el.click();
          return `✅ Clicked "${shortDesc}"`;

        case 'type':
          if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
            el.value = value;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return `✅ Typed "${value}" into "${shortDesc}"`;
          }
          return `❌ Element "${shortDesc}" is not an input`;

        case 'select':
          if (el instanceof HTMLSelectElement) {
            el.value = value;
            if (el.value !== value) {
                let found = false;
                Array.from(el.options).forEach((opt, idx) => {
                    if (opt.text.toLowerCase().includes(value.toLowerCase())) {
                        el.selectedIndex = idx;
                        found = true;
                    }
                });
                if (!found) return `❌ Option "${value}" not found in "${shortDesc}"`;
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return `✅ Selected "${value}" in "${shortDesc}"`;
          }
          return `❌ Element "${shortDesc}" is not a dropdown`;

        default:
          return `❌ Unknown action: ${action}`;
      }
    } catch (e) {
      return `❌ Execution Error: ${e}`;
    }
  }

  private isVisible(el: HTMLElement): boolean {
      return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  private cleanText(str: string): string {
    return str.replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  private highlightElement(el: HTMLElement) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const originalOutline = el.style.outline;
    const originalTransition = el.style.transition;
    el.style.transition = 'all 0.3s';
    el.style.outline = '3px solid #e55353'; 
    setTimeout(() => {
      el.style.outline = originalOutline;
      el.style.transition = originalTransition;
    }, 1000);
  }
}