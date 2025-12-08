import { Injectable } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { computeAccessibleName } from 'dom-accessibility-api';

@Injectable({
  providedIn: 'root'
})
export class AgentService {
  private uniqueIdCounter = 0;

  constructor(private router: Router) {}

  // --- Sitemap Logic ---
  public getRouteInfo() {
    const routes = this.flattenRoutes(this.router.config);
    const signature = this.generateSignature(routes);
    return { routes, version_hash: signature };
  }

  private flattenRoutes(routes: Routes, parentPath = ''): any[] {
    let flatList: any[] = [];
    routes.forEach(route => {
      if (route.redirectTo || (!route.path && !parentPath)) return;
      let fullPath = route.path ? `${parentPath}/${route.path}` : parentPath;
      fullPath = fullPath.replace('//', '/');
      flatList.push({
        path: fullPath,
        data: route.data || {},
        title: route.title || (route.data ? route.data['title'] : '') || this.formatPath(route.path)
      });
      if (route.children) flatList = flatList.concat(this.flattenRoutes(route.children, fullPath));
    });
    return flatList;
  }

  private formatPath(path: string | undefined): string {
    if (!path) return 'Home';
    return path.charAt(0).toUpperCase() + path.slice(1);
  }

  private generateSignature(routes: any[]): string {
    const routeString = routes.map(r => r.path + '|' + r.title).sort().join(';;');
    let hash = 0;
    for (let i = 0; i < routeString.length; i++) {
      const char = routeString.charCodeAt(i);
      hash = ((hash << 5) - hash) + char;
      hash = hash & hash; 
    }
    return hash.toString(16);
  }

  /**
   * 🧠 Smart Page Title Extraction
   */
  private getSmartPageTitle(): string {
    const sidebarActive = document.querySelector('.sidebar .nav-link.active, .c-sidebar .nav-link.active');
    if (sidebarActive) {
        const text = this.cleanText(sidebarActive.textContent || '');
        if (text) return text;
    }

    const h1 = document.querySelector('h1, .h1, c-card-header, .card-header strong');
    if (h1 && h1.textContent) {
        return this.cleanText(h1.textContent);
    }

    const breadcrumbActive = document.querySelector('.breadcrumb-item.active, .breadcrumb li:last-child');
    if (breadcrumbActive && breadcrumbActive.textContent) {
        return this.cleanText(breadcrumbActive.textContent);
    }

    return document.title;
  }

  /**
   * 🧠 Semantic Structure Extraction
   */
  public getPageStructure(): any {
    const containerSelectors = ['main', '.sidebar', '.header', 'c-card', '.card', 'form', '.modal-content'];
    const smartTitle = this.getSmartPageTitle();

    const structure: any = {
      url: window.location.hash || window.location.pathname,
      title: smartTitle,
      sections: [] 
    };

    const elements = document.querySelectorAll('button, a, input, select, textarea, h1, h2, h3, h4, h5, h6');
    elements.forEach(el => {
      if (!this.isVisible(el as HTMLElement)) return;
      const text = this.cleanText(el.textContent || (el as HTMLInputElement).value || '');
      if (!text && el.tagName !== 'INPUT' && el.tagName !== 'SELECT') return;

      const path = this.calculateSemanticPath(el as HTMLElement, containerSelectors);
      structure.sections.push({ text: text, tag: el.tagName.toLowerCase(), path: path });
    });
    return structure;
  }

  /**
   * 🔥🔥 UPDATED: Semantic Path Calculation with Nested Sidebar Support
   */
  private calculateSemanticPath(el: HTMLElement, selectors: string[]): string[] {
    const path: string[] = [];
    let current = el.parentElement;

    while (current && current.tagName !== 'BODY') {
      
      // 🔥 Logic 1: Detect CoreUI/Bootstrap Sidebar Groups (Sub-menus)
      // Structure: li.nav-group > a.nav-group-toggle (Parent) + ul (Children)
      if (current.classList.contains('nav-group') || current.classList.contains('c-sidebar-nav-dropdown')) {
          const toggle = current.querySelector('.nav-group-toggle, .c-sidebar-nav-dropdown-toggle');
          if (toggle && toggle.textContent) {
              const groupName = this.cleanText(toggle.textContent);
              // Prevent duplicates (e.g. if we clicked the toggle itself)
              if (groupName && groupName !== this.cleanText(el.innerText)) {
                  path.unshift(groupName); 
              }
          }
      }

      // 🔥 Logic 2: Standard Container Detection
      for (const selector of selectors) {
        if (current.matches(selector)) {
          const name = this.getContainerName(current);
          if (name) path.unshift(name);
          else path.unshift(selector.replace('.', ''));
          break; 
        }
      }
      current = current.parentElement;
    }
    
    // Deduplicate and limit depth
    return [...new Set(path)].slice(-4); 
  }

  private getContainerName(el: HTMLElement): string | null {
    if (el.classList.contains('card') || el.tagName === 'C-CARD') {
      const header = el.querySelector('.card-header, c-card-header');
      if (header) return this.cleanText(header.textContent || '');
    }
    if (el.classList.contains('sidebar')) return 'Sidebar';
    if (el.tagName === 'FORM') return 'Form';
    if (el.tagName === 'MAIN') return 'Main Content';
    return null;
  }

  // --- Agent Scanning & Execution (Existing Logic) ---
  scanPage(): string {
    const report: string[] = [];
    this.uniqueIdCounter = 1;
    const elements = document.querySelectorAll('*'); 
    elements.forEach((node) => {
      const el = node as HTMLElement;
      if (!this.isVisible(el)) return;
      if (el.closest('.agent-chat-container')) return;
      
      const tagName = el.tagName.toLowerCase();
      const interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'details'];
      const interactiveRoles = ['button', 'link', 'checkbox', 'radio', 'textbox', 'listbox', 'combobox', 'menuitem', 'tab'];
      const role = el.getAttribute('role');
      const isInteractive = interactiveTags.includes(tagName) || (role && interactiveRoles.includes(role));
      if (!isInteractive) return;

      const agentId = this.uniqueIdCounter++;
      el.setAttribute('data-agent-id', agentId.toString());

      const type = el.getAttribute('type') || '';
      const href = el.getAttribute('href') || '';
      const name = el.getAttribute('name') || '';
      const testId = el.getAttribute('data-testid') || el.id || '';
      
      let attrParts = [];
      if (type) attrParts.push(`type="${type}"`);
      if (href && href !== '#' && !href.startsWith('javascript')) attrParts.push(`href="${href}"`);
      if (name) attrParts.push(`name="${name}"`);
      if (testId) attrParts.push(`id="${testId}"`);
      
      const attrsStr = attrParts.length > 0 ? ' ' + attrParts.join(' ') : '';
      let finalDesc = this.getElementDescription(el);

      if (el.classList.contains('active') || el.getAttribute('aria-current') === 'page') finalDesc += ' [Active]';

      let stateInfo = '';
      if (tagName === 'input') {
        if (type === 'checkbox' || type === 'radio') stateInfo = `[Checked: ${(el as HTMLInputElement).checked}]`;
        else stateInfo = `[Value: "${(el as HTMLInputElement).value}"]`;
      } else if (tagName === 'select') {
        const select = el as HTMLSelectElement;
        const selectedOption = select.options[select.selectedIndex];
        stateInfo = `[Selected: "${selectedOption ? selectedOption.text.trim() : select.value}"]`;
      }
      report.push(`[${agentId}] <${tagName}${attrsStr}> "${finalDesc}" ${stateInfo}`);
    });
    return report.join('\n');
  }

  public getElementDescription(el: HTMLElement): string {
      let accName = computeAccessibleName(el);
      if (!accName && el.innerText) accName = this.cleanText(el.innerText);
      const hierarchy = this.getHierarchyPath(el);
      const structure = this.getStructuralContext(el);
      let desc = accName;
      if (hierarchy) if (!accName.includes(hierarchy)) desc = `${hierarchy} > ${accName}`;
      if (structure) desc = `[${structure}] ${desc}`;
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
      if (foundTitle && foundTitle.length > 0 && foundTitle.length < 40 && !paths.includes(foundTitle)) paths.unshift(foundTitle);
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
                    if (opt.text.trim().toLowerCase() === value.trim().toLowerCase()) {
                        el.selectedIndex = idx;
                        found = true;
                    }
                });
                if (!found) el.value = value; 
            }
            el.dispatchEvent(new Event('change', { bubbles: true }));
            return `✅ Selected "${value}" in "${shortDesc}"`;
          }
          return `❌ Element "${shortDesc}" is not a dropdown`;
        default:
          return `❌ Unknown action: ${action}`;
      }
    } catch (e) { return `❌ Execution Error: ${e}`; }
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
    el.style.outline = '3px solid #e55353'; 
    setTimeout(() => { el.style.outline = originalOutline; }, 1000);
  }
}