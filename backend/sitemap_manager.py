import json
import os
import datetime
import re

class SitemapManager:
    def __init__(self, filepath="sitemap_knowledge.json"):
        self.filepath = filepath
        self.data = {
            "version": "",
            # Key: Button Text, Value: Path String (e.g., "Icons > CoreUI Flags")
            "global_nav": {}, 
            "pages": {} 
        }
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                if "global_nav" not in self.data: self.data["global_nav"] = {}
                print(f"🗺️  Sitemap Loaded: {len(self.data['pages'])} pages.")
            except Exception as e:
                print(f"⚠️ Sitemap corrupted ({e}), starting fresh.")

    def save(self):
        try:
            with open(self.filepath, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Failed to save sitemap: {e}")

    def sync_skeleton(self, frontend_routes, frontend_version):
        """
        Syncs skeleton. Force save if file is missing even if version matches.
        """
        file_exists = os.path.exists(self.filepath)
        
        if self.data.get("version") == frontend_version and file_exists:
            print(f"✅ Sitemap version {frontend_version} is up to date.")
            return

        print(f"🔄 Sitemap update detected! ({self.data.get('version')} -> {frontend_version})")
        
        new_urls = set()
        for r in frontend_routes:
            raw_path = r['path']
            if not raw_path.startswith('/'): raw_path = '/' + raw_path
            path = "#" + raw_path
            new_urls.add(path)
            
            if path not in self.data["pages"]:
                self.data["pages"][path] = {
                    "title": r['title'],
                    "elements": [], 
                    "last_visited": None
                }
            else:
                self.data["pages"][path]["title"] = r['title']

        current_urls = list(self.data["pages"].keys())
        for url in current_urls:
            if url not in new_urls: del self.data["pages"][url]

        self.data["version"] = frontend_version
        self.save()
        print(f"🗺️  Sitemap Synced & Saved: {len(new_urls)} active pages.")

    def update_flesh(self, structure_data):
        """
        Updates content and Global Nav with hierarchy.
        """
        if not structure_data: return
        url = structure_data.get('url')
        new_title = structure_data.get('title')
        if not url: return

        if url not in self.data["pages"]:
            self.data["pages"][url] = {
                "title": new_title or "Unknown",
                "elements": [],
                "last_visited": None
            }

        # 1. Title Protection
        current_title = self.data["pages"][url].get("title", "")
        is_generic = "CoreUI" in new_title and "Admin" in new_title
        if new_title and not is_generic:
            self.data["pages"][url]["title"] = new_title

        # 2. Content & Nav Extraction
        keywords = set()
        ignored_regions = {'Sidebar', 'Header', 'Footer', 'Nav'}

        for item in structure_data.get('sections', []):
            text = item.get('text', '')
            path = item.get('path', []) 
            
            # Check global region
            is_global = any(region in path for region in ignored_regions)
            
            if is_global:
                # 🔥🔥 Store Hierarchical Global Nav
                # If it's a link in the sidebar
                if item['tag'] == 'a' and len(text) > 2:
                    # Filter 'Sidebar' itself to get the parent group (e.g. 'Icons')
                    meaningful_path = [p for p in path if p not in ignored_regions]
                    
                    if meaningful_path:
                        # Store as "Icons > CoreUI Flags"
                        path_str = " > ".join(meaningful_path)
                        self.data["global_nav"][text] = path_str
                    else:
                        self.data["global_nav"][text] = "Root"
            else:
                # Main Content
                if len(text) > 2 and len(text) < 50:
                    keywords.add(text)
                for p in path:
                    if p not in ignored_regions: keywords.add(p)

        if keywords:
            self.data["pages"][url]["elements"] = list(keywords)
            self.data["pages"][url]["last_visited"] = datetime.datetime.now().isoformat()
            self.save()

    def find_best_page(self, user_goal):
        """
        Search Pages first, then Global Nav with hierarchy hint.
        """
        best_url = None
        max_score = 0
        reason = ""
        
        goal_words = set(re.findall(r'\w+', user_goal.lower()))
        if not goal_words: return None, ""

        # 1. Search Pages
        for url, data in self.data["pages"].items():
            score = 0
            if any(w in url.lower() for w in goal_words): score += 3
            
            title = data.get('title', '').lower()
            if any(w in title for w in goal_words): score += 5
            
            hits = 0
            for elem in data.get('elements', []):
                if any(w in elem.lower() for w in goal_words): hits += 1
            score += min(hits, 10)
            
            if score > max_score:
                max_score = score
                best_url = url
                reason = f"Matched page '{data.get('title')}'."

        # 2. 🔥 Search Global Nav with Hierarchy Hint
        if max_score < 2:
            for nav_text, nav_path in self.data["global_nav"].items():
                if any(w in nav_text.lower() for w in goal_words):
                    if nav_path and nav_path != "Root":
                        return None, f"Found '{nav_text}' in Sidebar under '{nav_path}'. First expand '{nav_path}'."
                    else:
                        return None, f"Found '{nav_text}' in Sidebar. Try clicking it."

        if max_score > 2:
            return best_url, reason
        return None, ""