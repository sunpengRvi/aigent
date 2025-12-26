import os
import json
import chromadb
import re  # [NEW] 用于正则匹配
from openai import AsyncOpenAI

class PlannerBrain:
    def __init__(self, model_name="deepseek-r1:14b"):
        self.model_name = model_name
        self.client = AsyncOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY", "ollama"),
            base_url=os.environ.get("OLLAMA_HOST", "http://localhost:11434/v1")
        )
        self.chroma = chromadb.PersistentClient(path="./agent_brain_db")
        self.demo_coll = self.chroma.get_collection("demonstrations")

    def _simplify_steps(self, steps_json):
        """
        清洗数据，同时保留【图片路径】作为元数据
        Returns: (text_summary_list, image_map_dict)
        """
        steps = json.loads(steps_json)
        summary = []
        image_map = {} # Key: "Action -> Desc", Value: "path/to/crop.jpg"
        
        for s in steps:
            action = s.get('action')
            if isinstance(action, dict): action = action.get('type')
            desc = s.get('element_desc', 'Unknown Element')
            val = s.get('value', '')
            
            # 构造唯一键
            step_str = f"{action} -> {desc}"
            if val: step_str += f" ('{val}')"
            
            summary.append(step_str)
            
            # 🔥 [NEW] 提取视觉锚点
            if s.get('crop_image_path'):
                image_map[step_str] = s.get('crop_image_path')
                
        return summary, image_map

    async def generate_plan(self, user_goal, sitemap_context=""):
        print(f"🧠 [Planner] Thinking about: {user_goal}...")
        
        results = self.demo_coll.query(query_texts=[user_goal], n_results=3)
        if not results['documents'][0]: return None

        # 1. 收集所有参考步骤和图片
        ref_text = ""
        all_visual_anchors = {} # 合并所有 Demo 的图片映射
        
        for i, doc in enumerate(results['documents'][0]):
            steps, img_map = self._simplify_steps(results['metadatas'][0][i]['steps'])
            all_visual_anchors.update(img_map) # 简单的合并策略
            ref_text += f"\nExample #{i+1}:\n" + "\n".join([f"- {s}" for s in steps])

        # 2. 生成文本计划
        prompt = f"""
        Goal: "{user_goal}"
        Sitemap Hints: {sitemap_context}
        Reference Experiences:
        {ref_text}
        
        TASK: Create a concise plan.
        - Use specific element names from references.
        - Output strictly a numbered list.
        """
        
        try:
            resp = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1
            )
            raw_plan = resp.choices[0].message.content
            if "<think>" in raw_plan: raw_plan = raw_plan.split("</think>")[-1]
            
            text_steps = [line.strip() for line in raw_plan.split('\n') if line.strip() and (line[0].isdigit() or line.startswith('-'))]
            
            # 3. 🔥 [NEW] 将生成的计划与参考图片进行“模糊匹配”
            structured_plan = []
            for step in text_steps:
                # 去掉序号 "1. "
                clean_step = re.sub(r'^\d+\.\s*', '', step)
                
                best_img = None
                # 简单的文本包含匹配 (Visual Grounding Logic)
                # 如果生成的计划步骤包含参考步骤的关键描述，就认为可以用那张图
                for ref_key, img_path in all_visual_anchors.items():
                    # ref_key 比如 "click -> Radio 2"
                    # clean_step 比如 "Click Radio 2"
                    # 提取核心词（去掉 action）
                    core_ref = ref_key.split('->')[-1].strip().lower()
                    if len(core_ref) > 3 and core_ref in clean_step.lower():
                        best_img = img_path
                        break
                
                structured_plan.append({
                    "text": clean_step,
                    "image": best_img # 可能是 None
                })
                
            return structured_plan
            
        except Exception as e:
            print(f"❌ Planner Error: {e}")
            return None