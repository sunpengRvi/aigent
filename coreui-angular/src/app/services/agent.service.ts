import { Injectable } from '@angular/core';
// 👇 Import standard accessibility computation library (Core Upgrade)
import { computeAccessibleName } from 'dom-accessibility-api';

@Injectable({
  providedIn: 'root'
})
export class AgentService {
  private uniqueIdCounter = 0;

  constructor() {}

  /**
   * 👁️ [Eyes] v6: Standard Accessibility Scan + Deep Context
   * Scans the page for interactive elements, assigns unique IDs, and generates descriptive labels using standard accessibility rules.
   */
  scanPage(): string {
    const report: string[] = [];
    this.uniqueIdCounter = 1;

    // Scan all elements, relying on the standard library and logic to filter
    const elements = document.querySelectorAll('*'); 

    elements.forEach((node) => {
      const el = node as HTMLElement;
      
      // 1. Basic Filtering: Invisible, Agent itself
      if (!this.isVisible(el)) return;
      if (el.closest('.agent-chat-container')) return;
      
      // 2. Interactivity Check
      // We only care about elements the user can interact with
      const tagName = el.tagName.toLowerCase();
      const interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'details'];
      const interactiveRoles = ['button', 'link', 'checkbox', 'radio', 'textbox', 'listbox', 'combobox', 'menuitem', 'tab'];
      const role = el.getAttribute('role');

      const isInteractive = interactiveTags.includes(tagName) || (role && interactiveRoles.includes(role));

      // Skip non-interactive elements (unless they have explicit onclick, which is hard to detect reliably)
      if (!isInteractive) return;

      // 3. Tagging: Assign unique Agent ID
      const agentId = this.uniqueIdCounter++;
      el.setAttribute('data-agent-id', agentId.toString());

      const type = el.getAttribute('type') || '';

      // 🔥 4. Compute "Accessible Name" using standard library
      // This automatically handles <label for>, aria-label, aria-labelledby, placeholder, title, alt, etc.
      // This is much more robust than custom logic.
      let accName = computeAccessibleName(el);
      
      // Fallback strategy: If the standard library returns empty (e.g., icon-only button without aria), try innerText
      if (!accName && el.innerText) {
          accName = this.cleanText(el.innerText);
      }

      // 5. Get Hierarchy Context (Retain v5 logic for Admin Templates)
      const context = this.getHierarchyPath(el);
      
      // 6. Combine Description
      // Format: [Grandparent > Parent] Element Name
      let finalDesc = accName;
      if (context) {
         // Prevent duplication if context is already part of the name (e.g. Card Title is also Button Text)
         if (!accName.includes(context)) {
             finalDesc = `[${context}] ${accName}`;
         } else {
             finalDesc = `[${context}]`; 
         }
      }
      
      // If absolutely no description found, mark as Unnamed (AI likely cannot operate this)
      if (!finalDesc || finalDesc.trim() === '') {
          // Last resort: check ID or Class for hints
          finalDesc = el.id ? `#${el.id}` : 'Unnamed Element';
      }

      // Truncate long descriptions
      if (finalDesc.length > 120) finalDesc = finalDesc.substring(0, 120) + '...';

      // 7. State Info (Value / Checked)
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

      report.push(`[${agentId}] <${tagName}${type ? ' type="' + type + '"' : ''}> "${finalDesc}" ${stateInfo}`);
    });

    return report.join('\n');
  }

  // 🧠 Get Hierarchy Path (Card > Group) - Reused from v5 logic
  // Climbs up the DOM to find semantic container titles (Cards, Modals, Fieldsets)
  private getHierarchyPath(el: HTMLElement): string {
    const paths: string[] = [];
    let parent = el.parentElement;
    let depth = 0;

    // Look up to 8 levels deep
    while (parent && depth < 8) {
      const classList = parent.classList;
      const tagName = parent.tagName;
      let foundTitle = '';

      // A. Card / Widget
      if (classList.contains('card') || classList.contains('c-card') || classList.contains('card-body')) {
        // Try to find header at the same level or parent level depending on structure
        const card = classList.contains('card-body') ? parent.parentElement : parent;
        const header = card?.querySelector('.card-header, .c-card-header');
        if (header) foundTitle = this.cleanText(header.textContent || '');
      }
      // B. Form Group / Row
      else if (classList.contains('row') || classList.contains('mb-3') || classList.contains('form-group')) {
        const groupLabel = parent.querySelector('label, legend, h6, h5');
        if (groupLabel) {
            const forAttr = groupLabel.getAttribute('for');
            // Avoid using the element's own direct label as a context header
            if (!forAttr || forAttr !== el.id) {
                foundTitle = this.cleanText(groupLabel.textContent || '');
            }
        }
      }
      // C. Fieldset
      else if (tagName === 'FIELDSET') {
        const legend = parent.querySelector('legend');
        if (legend) foundTitle = this.cleanText(legend.textContent || '');
      }
      // D. Modal
      else if (classList.contains('modal-content')) {
        const title = parent.querySelector('.modal-title');
        if (title) foundTitle = this.cleanText(title.textContent || '');
      }

      // Add found title to path if unique and short enough
      if (foundTitle && foundTitle.length > 0 && foundTitle.length < 40 && !paths.includes(foundTitle)) {
        paths.unshift(foundTitle);
      }
      parent = parent.parentElement;
      depth++;
    }
    return paths.join(' > ');
  }

  // ✋ Execute Command (DOM Manipulation)
  executeCommand(action: string, id: string, value: string = ''): string {
    const el = document.querySelector(`[data-agent-id="${id}"]`) as HTMLElement;
    
    if (!el) return `❌ ID [${id}] not found (Try scanning again)`;

    this.highlightElement(el);

    try {
      switch (action) {
        case 'click':
          el.click();
          return `✅ Clicked [${id}]`;

        case 'type':
          if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
            el.value = value;
            // Dispatch events to notify Angular/Framework of changes
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return `✅ Typed "${value}"`;
          }
          return `❌ Element [${id}] is not an input`;

        case 'select':
          if (el instanceof HTMLSelectElement) {
            // Try matching by value first
            el.value = value;
            // If value match fails, try fuzzy text match
            if (el.value !== value) {
                let found = false;
                Array.from(el.options).forEach((opt, idx) => {
                    if (opt.text.toLowerCase().includes(value.toLowerCase())) {
                        el.selectedIndex = idx;
                        found = true;
                    }
                });
                if (!found) return `❌ Option "${value}" not found in select`;
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return `✅ Selected "${value}"`;
          }
          return `❌ Element [${id}] is not a dropdown`;

        default:
          return `❌ Unknown action: ${action}`;
      }
    } catch (e) {
      return `❌ Execution Error: ${e}`;
    }
  }

  // Helper: Check visibility
  private isVisible(el: HTMLElement): boolean {
      return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  }

  // Helper: Clean text
  private cleanText(str: string): string {
    return str.replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
  }

  // Helper: Visual feedback (Highlight)
  private highlightElement(el: HTMLElement) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    const originalOutline = el.style.outline;
    const originalTransition = el.style.transition;
    
    el.style.transition = 'all 0.3s';
    el.style.outline = '3px solid #e55353'; // CoreUI Red
    el.style.boxShadow = '0 0 10px rgba(229, 83, 83, 0.5)';

    setTimeout(() => {
      el.style.outline = originalOutline;
      el.style.boxShadow = 'none';
      el.style.transition = originalTransition;
    }, 1000);
  }
  
  // 🔥 Public Method: Get Semantic Description (Used by RecordingService)
  // Ensures consistency between recording logs and execution scans
  public getElementDescription(el: HTMLElement): string {
      let accName = computeAccessibleName(el);
      if (!accName && el.innerText) accName = this.cleanText(el.innerText);
      
      const context = this.getHierarchyPath(el);
      let desc = accName;
      
      if (context && !accName.includes(context)) {
          desc = `[${context}] ${accName}`;
      }
      return desc || 'Unknown Element';
  }
}