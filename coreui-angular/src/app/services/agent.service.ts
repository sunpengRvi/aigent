import { Injectable } from '@angular/core';
import { Router, Routes } from '@angular/router';
import { computeAccessibleName } from 'dom-accessibility-api';
import html2canvas from 'html2canvas';

@Injectable({
  providedIn: 'root'
})
export class AgentService {
  private uniqueIdCounter = 0;

  constructor(private router: Router) {}

  // =========================================================================
  // 📸 Visual Anchor Logic (New Feature)
  // =========================================================================
  async captureElementCrop(el: HTMLElement): Promise<string | null> {
    if (!el || !this.isVisible(el)) return null;

    try {
      // Create a specific canvas for the element
      const canvas = await html2canvas(el, {
        backgroundColor: null, 
        scale: 1,              
        logging: false,
        useCORS: true,         
        allowTaint: true
      });

      // Quality 0.8 is sufficient for training
      return canvas.toDataURL('image/jpeg', 0.8);
    } catch (e) {
      console.warn('⚠️ Failed to capture element crop:', e);
      return null;
    }
  }

  // =========================================================================
  // 🗺️ Sitemap & Structure Logic
  // =========================================================================
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

  private calculateSemanticPath(el: HTMLElement, selectors: string[]): string[] {
    const path: string[] = [];
    let current = el.parentElement;
    while (current && current.tagName !== 'BODY') {
      if (current.classList.contains('nav-group') || current.classList.contains('c-sidebar-nav-dropdown')) {
          const toggle = current.querySelector('.nav-group-toggle, .c-sidebar-nav-dropdown-toggle');
          if (toggle && toggle.textContent) {
              const groupName = this.cleanText(toggle.textContent);
              if (groupName && groupName !== this.cleanText(el.innerText)) path.unshift(groupName); 
          }
      }
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

  // =========================================================================
  // 👁️ CV Capture Logic (Fixed + Sticky Element Patch)
  // =========================================================================
  async captureContext(): Promise<any> {
    // 0. Wait Strategy
    if (document.readyState !== 'complete') {
        await new Promise(resolve => window.addEventListener('load', resolve, { once: true }));
    }
    await document.fonts.ready;
    await new Promise(resolve => setTimeout(resolve, 800)); 
    await new Promise(resolve => requestAnimationFrame(resolve));

    // 1. Scan & Extract
    const domTree = this.scanPage();
    const pageStructure = this.getPageStructure();
    const elementsMeta = this.extractElementCoordinates();
    
    // Current Scroll & Viewport
    const vWidth = window.innerWidth;
    const vHeight = window.innerHeight;
    const scrollY = window.scrollY;
    const scrollX = window.scrollX;

    let screenshotBase64 = '';
    try {
        const canvas = await html2canvas(document.body, {
            useCORS: true,
            logging: false,
            scale: 1,
            // Align viewport top-left to canvas (0,0)
            scrollY: -scrollY, 
            scrollX: -scrollX,
            width: vWidth,
            height: vHeight,
            windowWidth: vWidth,
            windowHeight: vHeight,
            
            // 🔥🔥 FIX: Handle 'fixed' AND 'sticky' elements 🔥🔥
            onclone: (clonedDoc) => {
                const allElements = clonedDoc.getElementsByTagName('*');
                
                for (let i = 0; i < allElements.length; i++) {
                    const el = allElements[i] as HTMLElement;
                    const style = window.getComputedStyle(el);
                    const position = style.position;

                    // Only process Fixed or Sticky elements that are currently visible/active
                    if (position === 'fixed' || position === 'sticky') {
                        
                        // 1. Calculate original position
                        const rect = el.getBoundingClientRect(); 
                        
                        // 2. 🔥 CREATE SPACER (Crucial for Sticky) 🔥
                        if (position === 'sticky') {
                            const spacer = clonedDoc.createElement('div');
                            spacer.style.display = style.display;
                            spacer.style.width = style.width;
                            spacer.style.height = style.height;
                            spacer.style.marginTop = style.marginTop;
                            spacer.style.marginBottom = style.marginBottom;
                            spacer.style.marginLeft = style.marginLeft;
                            spacer.style.marginRight = style.marginRight;
                            spacer.style.padding = '0';
                            spacer.style.border = 'none';
                            spacer.style.visibility = 'hidden'; // Invisible placeholder
                            
                            // Insert before the element to occupy its original slot
                            if (el.parentNode) {
                                el.parentNode.insertBefore(spacer, el);
                            }
                        }

                        // 3. Freeze the element visually to Absolute
                        el.style.position = 'absolute';
                        el.style.top = (rect.top + scrollY) + 'px'; 
                        el.style.left = (rect.left + scrollX) + 'px';
                        el.style.width = rect.width + 'px'; 
                        el.style.height = rect.height + 'px';
                        el.style.margin = '0'; 
                        el.style.bottom = 'auto'; 
                        el.style.right = 'auto';
                        el.style.transform = 'none'; 
                    }
                }
            },
            
            ignoreElements: (element) => {
                return element.classList.contains('agent-chat-container') || 
                       element.tagName === 'VLAB-AGENT-CHAT'; 
            }
        });

        // 🔥 Manual Crop (Double Safety)
        const viewportCanvas = document.createElement('canvas');
        viewportCanvas.width = vWidth;
        viewportCanvas.height = vHeight;
        const ctx = viewportCanvas.getContext('2d');

        if (ctx) {
            ctx.drawImage(canvas, 0, 0, vWidth, vHeight, 0, 0, vWidth, vHeight);
            screenshotBase64 = viewportCanvas.toDataURL('image/jpeg', 0.6);
        } else {
            screenshotBase64 = canvas.toDataURL('image/jpeg', 0.6);
        }

    } catch (e) {
        console.error("Screenshot failed:", e);
    }

    return {
        dom: domTree,
        page_structure: pageStructure,
        screenshot: screenshotBase64,
        elements_meta: elementsMeta
    };
  }

  private extractElementCoordinates(): any[] {
    const metas: any[] = [];
    const elements = document.querySelectorAll('[data-agent-id]');
    
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    elements.forEach(el => {
        if (!this.isElementTrulyVisible(el as HTMLElement)) return;

        const id = el.getAttribute('data-agent-id');
        const rect = el.getBoundingClientRect();
        
        if (id) {
            metas.push({
                id: parseInt(id, 10),
                x: Math.round(rect.left),
                y: Math.round(rect.top),
                w: Math.round(rect.width),
                h: Math.round(rect.height)
            });
        }
    });
    return metas;
  }

  // =========================================================================
  // ⚙️ Scanning & Execution
  // =========================================================================
  
  private isElementTrulyVisible(el: HTMLElement): boolean {
      if (!el.offsetWidth || !el.offsetHeight) return false;
      const rect = el.getBoundingClientRect();
      
      if (rect.bottom < 0 || rect.top > window.innerHeight || 
          rect.right < 0 || rect.left > window.innerWidth) {
          return false;
      }

      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') < 0.1) {
          return false;
      }

      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      
      if (centerX >= 0 && centerX <= window.innerWidth && centerY >= 0 && centerY <= window.innerHeight) {
          const topElement = document.elementFromPoint(centerX, centerY);
          if (!topElement) return false;
          if (el.contains(topElement) || topElement.contains(el)) return true;
          if (topElement.tagName === 'LABEL' && (topElement as HTMLLabelElement).control === el) return true;
          return false;
      }
      return true;
  }

  scanPage(): string {
    const report: string[] = [];
    this.uniqueIdCounter = 1;
    const elements = document.querySelectorAll('*'); 
    elements.forEach((node) => {
      const el = node as HTMLElement;
      
      if (!this.isElementTrulyVisible(el)) return;
      if (el.closest('.agent-chat-container') || el.tagName === 'VLAB-AGENT-CHAT') return;
      
      const tagName = el.tagName.toLowerCase();
      const interactiveTags = ['a', 'button', 'input', 'select', 'textarea', 'summary', 'details', 'label'];
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
      } else if (tagName === 'label') {
          const prev = el.previousElementSibling;
          if (prev && prev.tagName === 'INPUT') {
              const inputPrev = prev as HTMLInputElement;
              if (inputPrev.type === 'checkbox' || inputPrev.type === 'radio') {
                   stateInfo = `[Checked: ${inputPrev.checked}]`;
              }
          }
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
      const info = this.detectElementType(el);
      if (info.type === 'group') {
          // 强制追加 [Group] 前缀和状态
          desc = `[Group] ${desc} (${info.state || 'Toggle'})`;
      } else if (info.type === 'link') {
          // 强制追加 [Link] 前缀
          desc = `[Link] ${desc}`;
      } else if (info.type === 'input') {
          // Input 保持原样，scanPage 里通常已经处理了 value
      } else if (el.tagName === 'LABEL' && el.classList.contains('btn')) {
          // Explicitly mark button-like labels
          desc = `[Button] ${desc}`; 
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
      if (foundTitle && foundTitle.length > 0 && foundTitle.length < 40 && !paths.includes(foundTitle)) paths.unshift(foundTitle);
      parent = parent.parentElement;
      depth++;
    }
    return paths.join(' > ');
  }

  private detectElementType(el: HTMLElement): { type: 'group' | 'link' | 'input' | 'button' | 'generic', state?: string } {
      // 1. 向上查找最近的“语义容器” (处理点击 span 实际上是点击父级 row 的情况)
      // 很多时候 aria-expanded 挂在父级的 tree-node 或 li 上
      const container = el.closest('[aria-expanded], a, button, label') as HTMLElement || el;

      // ==================================================
      // 规则 A: 显式的折叠状态 (WAI-ARIA 标准)
      // 适用于: MatTree, Bootstrap Accordion, CoreUI Sidebar, etc.
      // ==================================================
      if (container.hasAttribute('aria-expanded')) {
          const isExpanded = container.getAttribute('aria-expanded') === 'true';
          return { type: 'group', state: isExpanded ? 'Expanded' : 'Collapsed' };
      }

      // ==================================================
      // 规则 B: 链接特征判断
      // 适用于: 所有 standard <a> tag
      // ==================================================
      if (container.tagName === 'A') {
          const href = container.getAttribute('href');
          // 如果 href 是 "#", "javascript:void(0)", 或者空，通常它是折叠器(Group)
          if (!href || href === '#' || href.startsWith('javascript')) {
             return { type: 'group', state: 'Collapsed' }; // 默认假设
          }
          // 如果有具体的 URL (如 #/dashboard)，它绝对是跳转链接
          return { type: 'link' };
      }

      // ==================================================
      // 规则 C: 输入控件特征
      // ==================================================
      const tagName = container.tagName;
      if (tagName === 'INPUT' || tagName === 'SELECT' || tagName === 'TEXTAREA') {
          return { type: 'input' };
      }

      if (tagName === 'LABEL') {
          // 如果 Label 长得像按钮 (CoreUI/Bootstrap 的 .btn 类)
          if (container.classList.contains('btn')) {
              return { type: 'button' };
          }
          // 普通 Label 视为 Input 的一部分
          return { type: 'input' };
      }

      return { type: 'generic' };
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

  // 🔥 Runtime Guard & Executor
  executeCommand(action: string, id: string, value: string = ''): string {
    // 👇 [UPDATED] Smart Scroll Logic
    if (action === 'scroll') {
        const val = value.toLowerCase();
        let scrollContainer: Element | Window = window;
        let containerName = "Window";

        // 1. Smart Container Detection
        if (val.startsWith('sidebar')) {
            // Try to find the Sidebar Root
            const sidebarRoot = document.querySelector('.sidebar, .c-sidebar, app-sidebar, c-sidebar');
            
            if (sidebarRoot) {
                // A. Priority: ng-scrollbar viewport (Common in CoreUI / ngx-scrollbar)
                const ngViewport = sidebarRoot.querySelector('.ng-scroll-viewport, .ng-native-scrollbar-hider, .ng-scroll-content');
                
                // B. Fallback: Any truly "overflowing" child
                const scrollableChild = Array.from(sidebarRoot.querySelectorAll('div, ul, nav')).find(el => {
                     const style = window.getComputedStyle(el);
                     // Must be scrollable (content height > client height) AND have overflow enabled
                     return (el.scrollHeight > el.clientHeight) && 
                            (style.overflowY === 'auto' || style.overflowY === 'scroll' || style.overflowY === 'visible');
                });

                if (ngViewport) {
                    scrollContainer = ngViewport;
                    containerName = "Sidebar (ng-scrollbar)";
                } else if (scrollableChild) {
                    scrollContainer = scrollableChild;
                    containerName = "Sidebar (Inner)";
                } else {
                    // Fallback to Root
                    scrollContainer = sidebarRoot;
                    containerName = "Sidebar (Root)";
                }
            } else {
                return '❌ Error: Sidebar container not found';
            }
        }

        // 2. Execute Scroll & Verify
        const isUp = val.includes('up');
        const amount = window.innerHeight * 0.6;
        const behavior = 'smooth';
        
        // Record start position
        const startTop = scrollContainer instanceof Window ? scrollContainer.scrollY : (scrollContainer as Element).scrollTop;

        if (scrollContainer instanceof Window) {
            scrollContainer.scrollBy({ top: isUp ? -amount : amount, behavior: behavior });
        } else {
            (scrollContainer as Element).scrollBy({ top: isUp ? -amount : amount, behavior: behavior });
        }
        
        // 3. Return Verify Info
        return `✅ Scrolled ${containerName} ${isUp ? 'Up' : 'Down'} (Start: ${Math.round(startTop)})`;
    }

    const el = document.querySelector(`[data-agent-id="${id}"]`) as HTMLElement;
    if (!el) return `❌ ID [${id}] not found`;
    this.highlightElement(el);
    const elementDesc = this.getElementDescription(el); 
    const shortDesc = elementDesc.length > 50 ? elementDesc.substring(0, 50) + '...' : elementDesc;
    
    try {
      switch (action) {
        case 'click':
          if (el.tagName === 'LABEL') {
              el.click();
              return `✅ Clicked Label "${shortDesc}"`;
          }
          if (el instanceof HTMLSelectElement) {
              return `❌ Error: Element [${id}] is a <select> dropdown. 'click' will not change its value. You MUST use 'select' action with a 'value'.`;
          }
          if (el instanceof HTMLInputElement) {
              const type = el.type.toLowerCase();
              if (['text', 'password', 'email', 'number', 'search', 'tel', 'url'].includes(type)) {
                  return `❌ Error: Element [${id}] is a text input. 'click' will not change its value. You MUST use 'type' action with a 'value'.`;
              }
          }
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
}