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
      // 结构树不需要严格的遮挡检测，基本可见即可
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
  // 👁️ CV Capture Logic (Manual Crop Strategy)
  // =========================================================================
  async captureContext(): Promise<any> {
    // 0. 三重等待策略：确保页面渲染完毕
    if (document.readyState !== 'complete') {
        await new Promise(resolve => window.addEventListener('load', resolve, { once: true }));
    }
    await document.fonts.ready;
    // 800ms 缓冲，确保 Angular 动画和 DOM 变更彻底完成
    await new Promise(resolve => setTimeout(resolve, 800)); 
    await new Promise(resolve => requestAnimationFrame(resolve));

    // 1. 扫描页面 (使用严格的可见性检查)
    const domTree = this.scanPage();
    const pageStructure = this.getPageStructure();

    // 2. 提取坐标 (相对于视口)
    const elementsMeta = this.extractElementCoordinates();
    
    const vWidth = window.innerWidth;
    const vHeight = window.innerHeight;

    let screenshotBase64 = '';
    try {
        // 🔥 Step A: 使用 html2canvas 截取整个 body
        // scrollY: -window.scrollY 会将当前视口的内容“移”到画布的 (0,0) 位置
        // 这样可以规避滚动条导致的偏移
        const fullCanvas = await html2canvas(document.body, {
            useCORS: true,
            logging: false,
            scale: 1, // 强制 1:1 比例，方便坐标对齐
            scrollY: -window.scrollY, 
            scrollX: -window.scrollX,
            // 尝试限制渲染区域，虽然 html2canvas 有时会忽略，但值得加上
            //width: vWidth,
            //height: vHeight,
            //windowWidth: vWidth,
            //windowHeight: vHeight,
            ignoreElements: (element) => {
                return element.classList.contains('agent-chat-container') || 
                       element.tagName === 'VLAB-AGENT-CHAT'; 
            }
        });

        // 🔥 Step B: 手动裁剪 (二次保障)
        // 创建一个只包含当前视口大小的 Canvas，把 fullCanvas 的左上角画进去
        const viewportCanvas = document.createElement('canvas');
        viewportCanvas.width = vWidth;
        viewportCanvas.height = vHeight;
        const ctx = viewportCanvas.getContext('2d');

        if (ctx) {
            // 从源画布的 (0,0) 复制到 目标画布的 (0,0)
            ctx.drawImage(
                fullCanvas, 
                0, 0, vWidth, vHeight, 
                0, 0, vWidth, vHeight
            );
            screenshotBase64 = viewportCanvas.toDataURL('image/jpeg', 0.6);
        } else {
            screenshotBase64 = fullCanvas.toDataURL('image/jpeg', 0.6);
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
    
    // 我们只需要视口内的元素
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    elements.forEach(el => {
        // 🔥 必须使用严格可见性检查 (Hit Testing)
        if (!this.isElementTrulyVisible(el as HTMLElement)) return;

        const id = el.getAttribute('data-agent-id');
        const rect = el.getBoundingClientRect();
        
        if (id) {
            metas.push({
                id: parseInt(id, 10),
                // 坐标直接取 rect，因为它是相对于视口左上角的
                // 我们的截图也是强制对齐到视口左上角的，所以完美匹配
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
  
  // 🔥 严格的可见性检查 (Hit Testing + CSS + Bounds)
  private isElementTrulyVisible(el: HTMLElement): boolean {
      // 1. 尺寸检查
      if (!el.offsetWidth || !el.offsetHeight) return false;
      const rect = el.getBoundingClientRect();
      
      // 2. 视口边界检查 (完全在屏幕外的忽略)
      if (rect.bottom < 0 || rect.top > window.innerHeight || 
          rect.right < 0 || rect.left > window.innerWidth) {
          return false;
      }

      // 3. CSS 样式检查
      const style = window.getComputedStyle(el);
      if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') < 0.1) {
          return false;
      }

      // 4. 遮挡检查 (Hit Test)
      // 在元素中心点发射射线，看最顶层元素是不是自己
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      
      // 确保点在视口内
      if (centerX >= 0 && centerX <= window.innerWidth && centerY >= 0 && centerY <= window.innerHeight) {
          const topElement = document.elementFromPoint(centerX, centerY);
          if (!topElement) return false;
          
          // 如果点击到的是自己，或者自己的子/父元素，视为可见
          if (el.contains(topElement) || topElement.contains(el)) return true;
          
          // 特殊情况：Label 覆盖 Input (这在 Form 中很常见)
          if (topElement.tagName === 'LABEL' && (topElement as HTMLLabelElement).control === el) return true;
          
          return false; // 被弹窗、遮罩层或其他元素遮挡
      }

      return true;
  }

  scanPage(): string {
    const report: string[] = [];
    this.uniqueIdCounter = 1;
    const elements = document.querySelectorAll('*'); 
    elements.forEach((node) => {
      const el = node as HTMLElement;
      
      // 🔥 使用严格检查过滤幽灵元素
      if (!this.isElementTrulyVisible(el)) return;
      if (el.closest('.agent-chat-container') || el.tagName === 'VLAB-AGENT-CHAT') return;
      
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

  // 🔥 Runtime Guard: 前端拦截逻辑
  executeCommand(action: string, id: string, value: string = ''): string {
    const el = document.querySelector(`[data-agent-id="${id}"]`) as HTMLElement;
    if (!el) return `❌ ID [${id}] not found`;
    this.highlightElement(el);
    const elementDesc = this.getElementDescription(el); 
    const shortDesc = elementDesc.length > 50 ? elementDesc.substring(0, 50) + '...' : elementDesc;
    
    try {
      switch (action) {
        case 'click':
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