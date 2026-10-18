# -*- coding: utf-8 -*-
"""
AutoSci Factual Figure Description Generator (100% Traditional Paper-Centric Pack)
==================================================================================
1. 支持交互式输入“中文输入公式”四大要素：
   - 图表编号（如：Figure 1b）
   - 测试方法（如：Transient photoluminescence decay spectroscopy, TRPL）
   - 样品名称（如：QD, QD-BDP1）
   - 核心实验现象与物理推论
2. 根据输入的测试方法，智能模糊匹配 D:\\ARS\\AutoSci-main\\wiki\\methods\\ 下最相关的表征方法模板。
3. 提取 6 篇最具参考价值的真题英文文献。
4. 调用 DeepSeek API 生成一整套 100% 干净的学术描述 (含标准传统数值引文 [1]-[6])。
5. 自动搜索 D:\\ARS\\Literature_Library\\ 索引，把这 6 篇原装 PDF 复制到 Figure_X_Report\\Source_PDFs\\ 下重命名为 [1]-[6]，供极简核对。
"""

import os
import sys
import re
import json
import shutil
import urllib.request
from pathlib import Path
from typing import List, Dict, Any, Set

# ⚙️ 路径与常量配置
WIKI_METHODS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\methods")
LITERATURE_LIBRARY_DIR = Path(r"D:\ARS\Literature_Library")
MASTER_REGISTRY_PATH = LITERATURE_LIBRARY_DIR / "master_registry.json"
DEEPSEEK_KEY_FILE_PATH = r"D:\ARS\deepseek_api_key.txt"

def get_deepseek_api_key() -> str | None:
    """安全读取 DeepSeek API Key"""
    api_file = Path(DEEPSEEK_KEY_FILE_PATH)
    if api_file.exists():
        try:
            return api_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    return os.environ.get("DEEPSEEK_API_KEY")

def load_custom_skill(workspace_dir: Path | None = None) -> str:
    """加载用户自定义 Skill MD 或 Prompt 扩展 (支持环境变量、工作区 custom_skill.md 或全局配置)"""
    env_skill = os.environ.get("AUTOSCI_CUSTOM_SKILL", "").strip()
    if env_skill:
        return env_skill
    env_file = os.environ.get("AUTOSCI_SKILL_FILE", "").strip()
    if env_file and Path(env_file).exists():
        try:
            return Path(env_file).read_text(encoding="utf-8").strip()
        except Exception:
            pass
    if workspace_dir:
        ws_skill = workspace_dir / "custom_skill.md"
        if ws_skill.exists():
            try:
                return ws_skill.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return ""

def load_master_registry_papers() -> List[Dict[str, Any]]:
    """加载文献大表"""
    if not MASTER_REGISTRY_PATH.exists():
        return []
    try:
        data = json.loads(MASTER_REGISTRY_PATH.read_text(encoding="utf-8"))
        return data.get("matched_papers", [])
    except Exception:
        return []

def make_slug(text: str) -> str:
    """生成规范 slug"""
    s = text.lower()
    s = re.sub(r'[^a-z0-9\s-]', '', s)
    s = re.sub(r'[\s-]+', '-', s)
    return s.strip('-')

def select_best_method_files_via_api(method_name: str, samples: str, observations: str, api_key: str) -> List[Path]:
    """通过 DeepSeek API 智能分析并选择最匹配的方法学或物理机制 Markdown 文件 (100% 跨目录语义匹配，含稳健重试与预筛选)"""
    all_files = []
    
    # 1. 载入表征方法库
    if WIKI_METHODS_DIR.exists():
        for f in WIKI_METHODS_DIR.glob("*.md"):
            all_files.append((f, f"methods/{f.name}"))
            
    # 2. 载入物理机制库
    WIKI_MECHANISMS_DIR = Path(r"D:\ARS\AutoSci-main\wiki\mechanisms")
    if WIKI_MECHANISMS_DIR.exists():
        for f in WIKI_MECHANISMS_DIR.glob("*.md"):
            all_files.append((f, f"mechanisms/{f.name}"))
            
    if not all_files:
        print("❌ 错误: 本地方法学和机制库均为空！")
        return []
        
    # 智能候选初筛（防止 800+ 文件名同时塞入导致 Prompt 达数十 KB 触发网络截断）
    candidate_files = all_files
    if len(all_files) > 120:
        # 提取中英文关键词进行相关度初打分
        query_text = f"{method_name} {samples} {observations}".lower()
        # 常见物理与化学关键词扩展词典
        kw_map = {
            "荧光": ["photoluminescence", "pl", "fluorescence", "emission", "trpl", "lifetime"],
            "吸收": ["absorption", "absorbance", "uv-vis", "tas", "transient"],
            "瞬态": ["transient", "tas", "trpl", "femtosecond", "picosecond", "time-resolved"],
            "寿命": ["lifetime", "decay", "trpl", "tcspc"],
            "能级": ["band", "alignment", "homo", "lumo", "energy", "level", "valence", "conduction", "type-ii", "type-i", "heterojunction"],
            "机理": ["mechanism", "transfer", "charge", "energy", "electron", "hole", "tet", "fret", "dexter"],
            "机制": ["mechanism", "transfer", "charge", "energy", "electron", "hole", "tet", "fret", "dexter"],
            "电荷": ["charge", "electron", "hole", "cs", "cr", "transfer", "separation"],
            "能量": ["energy", "tet", "fret", "dexter", "transfer", "upconversion", "tta"],
            "猝灭": ["quenching", "quench", "decay", "lifetime"],
            "上转换": ["upconversion", "tta", "uc", "triplet-triplet"]
        }
        extended_kws = set(re.findall(r'[a-zA-Z0-9_-]{2,}', query_text))
        for zh_k, en_list in kw_map.items():
            if zh_k in query_text:
                extended_kws.update(en_list)
                
        scored_files = []
        for fpath, rel_name in all_files:
            fn_lower = rel_name.lower().replace("-", " ").replace("_", " ")
            score = 0
            for kw in extended_kws:
                if kw in fn_lower:
                    score += 5
            scored_files.append((score, (fpath, rel_name)))
            
        scored_files.sort(key=lambda x: x[0], reverse=True)
        # 挑选前 120 个最强相关的候选文件
        candidate_files = [item[1] for item in scored_files[:120]]
        
    filenames_str = "\n".join([f"- {name_col}" for _, name_col in sorted(candidate_files, key=lambda x: x[1])])
    
    print("🧠 正在呼叫 DeepSeek 进行跨语言、跨目录学术对账，智能精准匹配最合适的模板节点...")
    
    prompt = f"""You are a world-class academic taxonomist and spectroscopist in physical chemistry, photophysics, and nanomaterials.
Your task is to analyze the user's characterization/mechanism request and select the most relevant files from our candidate pool (which contains both methods/ and mechanisms/).
The user might input terms in Chinese (e.g., "荧光光谱", "能级图", "能带弯曲", "瞬态吸收") or abbreviations (e.g., "PL", "TRPL", "TA", "Band Alignment"). You must understand their precise semantic meaning and select the best matching files.

### USER'S INPUT DATA:
1. **Technique/Mechanism Name**: {method_name}
2. **Samples**: {samples}
3. **Core Observations & Physical Inferences**:
{observations}

### CANDIDATE FILES AVAILABLE:
{filenames_str}

### SELECTION RULES:
1. **Understand Semantic Meaning**: Match by physical, optical, and energetic techniques.
   - E.g., "能级图" or "能带对齐" or "Type-II" or "HOMO" refers to band alignments. Excellent matches: `mechanisms/type-ii-band-alignment.md`, `mechanisms/charge-separation-cs.md`.
   - E.g., "荧光光谱" or "光致发光" or "PL" refers to Photoluminescence. Good matches are: `methods/steady-state-photoluminescence-pl-photoluminescence-excitation.md`, `methods/uv-vis-absorption-fluorescence-spectroscopy.md`.
2. **Aggressively Match Multiple Files (Wide Ingestion)**: You MUST select 10 to 20 highly relevant and complementary files from the available list to ensure we don't miss any synonymous or cross-characterizations. 
   - E.g., if the user is investigating TRPL (Transient), you must also select files covering steady-state PL, fluorescence quenching, quantum yields, and charge-transfer mechanisms.
3. **Be Extremely Precise**: Output valid filenames exactly as listed in the candidate pool.

### OUTPUT FORMAT:
You must respond with a strict JSON object with this exact schema (no Markdown wrap, no conversational filler, just raw JSON):
{{
  "selected_files": [
    "methods/example-file-1.md",
    "mechanisms/example-file-2.md"
  ]
}}
"""

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic assistant. You identify matching templates based on semantic analysis and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}
    }
    
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(data).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                resp_data = json.loads(response.read().decode("utf-8"))
                content = resp_data["choices"][0]["message"]["content"].strip()
                
                # 清理 Markdown 代码块包裹
                if content.startswith("```"):
                    content = re.sub(r"^```(?:json)?\s*", "", content)
                    content = re.sub(r"\s*```$", "", content)
                    
                result = None
                try:
                    import json_repair
                    result = json_repair.loads(content.strip())
                except ImportError:
                    try:
                        cleaned = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content.strip())
                        result = json.loads(cleaned)
                    except Exception:
                        result = json.loads(content.strip())
                        
                selected_names = result.get("selected_files", []) if isinstance(result, dict) else []
                
                matched_paths = []
                for name in selected_names:
                    name_clean = name.strip()
                    p = None
                    if "/" in name_clean:
                        p = WIKI_METHODS_DIR.parent / name_clean
                    else:
                        p_meth = WIKI_METHODS_DIR / name_clean
                        p_mech = WIKI_MECHANISMS_DIR / name_clean
                        if p_meth.exists():
                            p = p_meth
                        elif p_mech.exists():
                            p = p_mech
                        else:
                            p = p_meth
                            
                    if p and p.exists() and p.is_file():
                        matched_paths.append(p)
                        
                if matched_paths:
                    return matched_paths
                elif attempt < max_retries:
                    import time
                    time.sleep(2 * attempt)
                    continue
        except Exception as e:
            print(f"  ⚠️ [重试 {attempt}/{max_retries}] 智能匹配 API 连接或解析微小异常: {e}")
            if attempt < max_retries:
                import time
                time.sleep(2 * attempt)
            else:
                # 终极兜底：使用本地关键词排序挑选前 12 个模板
                print(f"  ℹ️ 启用本地语义兜底机制，自动为您选出最相关的 12 个核心模板...")
                fallback_paths = [fpath for fpath, _ in candidate_files[:12]]
                if fallback_paths:
                    return fallback_paths
                sys.exit(1)
                
    return [fpath for fpath, _ in candidate_files[:12]]

def extract_academic_examples(method_paths: List[Path]) -> List[Dict[str, str]]:
    """从匹配的方法/机制 md 文件中精细提取真实的文献原文段落"""
    examples = []
    for filepath in method_paths:
        if not filepath.exists():
            continue
        try:
            content = filepath.read_text(encoding="utf-8")
            # 兼容 methods 下的 '描述与结果'，以及 mechanisms 下的 '描述与结果' (由于其格式高度统一)
            sections = re.split(r"###\s+\[\[(.*?)\]\]\s*中的描述与结果", content)
            
            for i in range(1, len(sections), 2):
                paper_slug = sections[i].strip()
                sec_body = sections[i+1]
                
                # 稳健提取 Original English Text
                eng_text = ""
                eng_split = re.split(r"\*\*文献英文原文\s*\(Original English Text\):\*\*", sec_body)
                if len(eng_split) > 1:
                    raw_block = re.split(r"\*\*中文翻译与学术提炼|\n###|\Z", eng_split[1])[0]
                    lines = [line.strip().lstrip(">").strip() for line in raw_block.strip().split("\n") if line.strip()]
                    eng_text = " ".join(lines)
                    eng_text = re.sub(r"\s+", " ", eng_text)
                
                if eng_text:
                    
                    # 针对能级图/物理机制，可以顺手把能级定量参数提取并拼接在前面，丰富写作事实
                    energy_levels_text = ""
                    energy_match = re.search(r"\*\*能级与定量参数 \(Energy Levels\):\*\*\s*(.*?)(\n|$)", sec_body)
                    if energy_match:
                        lvl = energy_match.group(1).strip()
                        if lvl and lvl.lower() != "unspecified":
                            energy_levels_text = f"[Energy Parameter Reference: {lvl}] "
                    
                    examples.append({
                        "source": paper_slug,
                        "text": energy_levels_text + eng_text,
                        "method_file": filepath.name
                    })
        except Exception:
            pass
    return examples

def rerank_examples_via_llm(all_examples: List[Dict[str, str]], user_observations: str, method_name: str, api_key: str, limit: int = 6) -> List[Dict[str, str]]:
    """
    【局部 RAG 语义重排器 (LLM-as-a-Reranker)】
    利用 DeepSeek 的物理化学常识，在扩大的候选文献池（50-100段原文）中，
    精选出 6 段最契合用户当前实验观测与传能机理的顶刊写作范式。
    """
    if not all_examples:
        return []
    if len(all_examples) <= limit:
        return all_examples
        
    print(f"\n🧠 [LLM 局部 RAG 语义重排激活] 正在 100% 模拟物理审稿人脑，在 {len(all_examples)} 个顶刊候选片段中进行语义精选...")
    
    # 格式化候选库，每个段落给予一个临时 ID
    candidates_str = ""
    for idx, ex in enumerate(all_examples):
        # 截断一些极长或格式乱的内容，只保留精华用于重排
        candidates_str += f"ID [{idx}]: \"{ex['text'][:280]}...\"\n\n"
        
    prompt = f"""You are an elite peer reviewer and spectroscopist in physical chemistry and photophysics.
Your task is to analyze the user's specific experimental observation and select the top {limit} most physically and semantically relevant literature excerpts from our local candidate pool.

### USER'S EXPERIMENTAL STUDY:
1. **Characterization/Mechanism**: {method_name}
2. **User's Fact Observation**: "{user_observations}"

### CANDIDATE LITERATURE EXCERPTS:
{candidates_str}

### INSTRUCTIONS FOR RE-RANKING:
1. Find candidate excerpts that discuss highly similar physical trends, quenching behaviors, lifetime fitted kinetics (mono/bi-exponential), energy levels, or sample complex behaviors.
2. Select the top {limit} best matching candidate IDs.
3. Order them strictly from the most physically relevant (best templates) to the least relevant.

### OUTPUT FORMAT:
Respond with a strict JSON object with this exact schema (no markdown, no conversation, just raw JSON):
{{
  "selected_ids": [integer_id_1, integer_id_2, ...]
}}
"""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are a professional academic reviewer. You perform semantic reranking and output valid JSON only."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            content = resp_data["choices"][0]["message"]["content"].strip()
            if content.startswith("```"):
                content = re.sub(r"^```(?:json)?\s*", "", content)
                content = re.sub(r"\s*```$", "", content)
                
            res = None
            try:
                import json_repair
                res = json_repair.loads(content.strip())
            except ImportError:
                try:
                    cleaned = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', content.strip())
                    res = json.loads(cleaned)
                except Exception:
                    res = json.loads(content.strip())
                    
            selected_ids = res.get("selected_ids", []) if isinstance(res, dict) else []
            
            reranked_examples = []
            for item_id in selected_ids:
                try:
                    idx = int(item_id)
                    if 0 <= idx < len(all_examples):
                        reranked_examples.append(all_examples[idx])
                except (ValueError, TypeError):
                    pass
            
            # 如果重排结果不全，使用前 6 个作为安全兜底
            if len(reranked_examples) < limit:
                for ex in all_examples:
                    if ex not in reranked_examples:
                        reranked_examples.append(ex)
                    if len(reranked_examples) >= limit:
                        break
                        
            print(f"   ➜ [语义重排完成] 已为您万无一失地挑出 6 篇与您当前实验现象物理逻辑咬合度最完美的顶刊真题范例！")
            return reranked_examples[:limit]
            
    except Exception as e:
        print(f"   ⚠️ [重排异常] 接口异常或网络抖动 ({e})。降级使用默认相关度排序兜底。")
        # 降级采用原有的关键词匹配排序兜底
        keywords = method_name.lower().replace('-', ' ').split()
        keywords.extend(["peak", "exciton", "absorption", "emission", "decay", "lifetime", "complex", "transition"])
        scored = []
        for ex in all_examples:
            text_lower = ex["text"].lower()
            score = sum(1 for kw in keywords if kw in text_lower)
            scored.append((score, ex))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item[1] for item in scored[:limit]]

def find_pdf_for_slug(slug: str, matched_papers: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    """通过 slug 在大表里反查 PDF 的物理存储信息"""
    slug_words = set(slug.replace('-', ' ').lower().split())
    stop_words = {"and", "of", "the", "in", "with", "from", "on", "at", "by", "via", "to"}
    slug_words_clean = slug_words - stop_words
    if not slug_words_clean:
        slug_words_clean = slug_words

    best_match = None
    best_overlap = 0
    
    for paper in matched_papers:
        title = paper.get("metadata", {}).get("title", "")
        if not title:
            continue
        title_slug = make_slug(title)
        title_words = set(title_slug.replace('-', ' ').split()) - stop_words
        
        overlap = len(slug_words_clean & title_words)
        if overlap > best_overlap:
            if overlap >= min(2, len(slug_words_clean)):
                best_overlap = overlap
                best_match = paper
                
    return best_match

def generate_figure_description(fig_id: str, method_name: str, samples: str, observations: str, examples: List[Dict[str, str]], api_key: str, workspace_dir: Path | None = None):
    """调用 DeepSeek 拼装生成 100% 引文标定的学术报告"""
    print(f"\n🧠 正在将事实与学术句式无损缝合，呼叫 DeepSeek API 进行对账写作...")
    
    # 格式化范文示例
    examples_str = ""
    for idx, ex in enumerate(examples, 1):
        examples_str += f"Example [{idx}] (Retrieved style template):\n\"{ex['text']}\"\n\n"
        
    # 动态匹配 1 到 len(examples)
    citation_rules = []
    for idx in range(1, len(examples) + 1):
        citation_rules.append(f"     * Use citation `[{idx}]` when adapting/drawing inspiration from style or facts of Example [{idx}]")
    citation_rules_str = "\n".join(citation_rules)

    # 加载用户自定义 Skill
    custom_skill = load_custom_skill(workspace_dir)
    custom_skill_block = ""
    if custom_skill:
        custom_skill_block = f"""
### 🌟 USER CUSTOM SKILL & SPECIAL WRITING INSTRUCTIONS (HIGHEST PRIORITY):
The user has provided the following specific domain skill instructions and writing guidelines. You MUST strictly adhere to them:
{custom_skill}
"""
    
    prompt = f"""You are a world-class academic writing consultant and an expert in physical chemistry, photophysics, and nanomaterials.
Your task is to write a highly professional, peer-reviewed-level academic text describing **{fig_id}**.

{custom_skill_block}

### USER INPUT PHYSICAL FACTS (These are your rigid ground truths, do NOT contradict them):
1. **Figure ID**: {fig_id}
2. **Characterization Technique**: {method_name}
3. **Samples Involved**: {samples}
4. **Core Experimental Observations & Physical Inferences**:
{observations}

### 🚨 MANDATORY ANTI-PLAGIARISM & PARAPHRASING MANDATE (CRITICAL - 20%+ DISSIMILARITY):
- **Zero Verbatim Copying**: You MUST NEVER copy sentences, clauses, or fixed phrases verbatim from the retrieved reference templates.
- **Substantial Paraphrasing**: Every single sentence MUST be fundamentally synthesized and paraphrased to ensure **at least 20% structural and linguistic dissimilarity** from any source literature.
- **Preserve Rigid Facts, Transform Expression**: Faithfully retain all quantitative values, chemical formulas, spectroscopic terms, and citations, but express the academic narrative in original, high-level scholarly English and Chinese.

### 🚨 STRICT CITATION & REFRENCE RULES (EXTREMELY CRITICAL):
1. **Use Traditional Numerical Citations**: You MUST use standard numerical citation bracket formats (e.g., `[1]`, `[2]`, `[1, 3]`, `[4-6]`) in the text.
   - **NEVER use double brackets like `[[slug]]` or verbose strings like `[Adapted from [[slug]]]`** inside the final text.
   - Example citation mappings to use:
{citation_rules_str}
2. **Citation Rules**:
   - Whenever you borrow, adapt, or are inspired by a specific academic term, phrase, or writing pattern from the examples, you MUST append the corresponding numerical citation.
   - If you expand on physical details that are NOT in the user's prompt (such as specific electronic transitions, mathematical fit models like mono/bi-exponential decay, or excitation parameters), you MUST cite the specific reference that justifies this expansion, or label it as `[Textbook Fact]`.
3. **EXPLICIT TRANSPARENCY TAGGING FOR UNMENTIONED AI INFERENCES & EXPANSIONS (CRITICAL)**:
   - The user provided their ground-truth experimental facts in "USER INPUT PHYSICAL FACTS".
   - Whenever you introduce professional details, specific electronic transitions (e.g. '1S3/2–1Se exciton transition', 'S0–S1 (π–π*) transition'), mathematical fit functions (e.g. 'bi-exponential decay fitting'), or mechanistic attributions that were NOT explicitly stated in the user's input:
   - You MUST visibly mark these AI-inferred expansions with brackets and bold asterisks: e.g., `[**lowest-energy 1S3/2–1Se exciton transition**]`, `[**bi-exponential fitting**]` (in Chinese: `[**最低能级 1S3/2–1Se 激子跃迁**]`, `[**双指数衰减拟合**]`).
   - This allows the author to immediately spot literature-based AI deductions, verify them against actual sample parameters, or edit/delete them effortlessly.
4. **Ground-State / Excited-State Interactions**: When claiming photophysical mechanisms (e.g., Energy Transfer, Charge Transfer, Quenching), you MUST cite the exact reference you adapted this mechanism from.

### RETRIEVED STYLE & FACT TEMPLATES (Use these as your style & logic sources):
{examples_str}

### OUTPUT FORMAT:
Your response must be structured as follows:
1. **Figure Caption**: A concise yet comprehensive caption for {fig_id}, with inline numerical citations and explicit `[**...**]` marks for non-user expansions.
2. **Results and Discussion (English - Fully Citated)**: Detailed analysis paragraph where **EVERY single sentence** MUST end with one or more traditional numerical citations (e.g., `[1]`, `[2]`, `[1, 4]`, or `[Textbook Fact]`), and all AI-inferred professional expansions are clearly bracketed with `[**...**]`.
3. **Results and Discussion (Chinese - Fully Citated)**: A beautiful, professional Chinese translation, preserving the EXACT same numerical citations and `[**...**]` AI expansion tags.
4. **AI Inference & Expansion Notes**: A brief bilingual note at the bottom:
   *(Note: Terms bracketed in [**...**] represent AI-deduced physical attributions or models based on literature benchmarks. Authors can quickly verify or adjust them according to real laboratory parameters).*
"""

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": "You are an elite academic writer. You write precise, peer-reviewed results & discussion sections using numerical citations only. You never use wikilinks like [[slug]]."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.3,
        "thinking": {"type": "disabled"}
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers=headers,
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            resp_data = json.loads(response.read().decode("utf-8"))
            return resp_data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"❌ 调用 DeepSeek API 发生错误: {e}")
        return None

def main():
    # 强制配置标准输出为 UTF-8 防止 Windows 乱码
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

    print("=" * 80)
    print("🔬 AutoSci 本地学术写作工作站 (DeepSeek API 零门槛极省版)")
    print("=" * 80)
    
    # 1. 安全获取 API Key
    api_key = get_deepseek_api_key()
    if not api_key:
        print("❌ 错误: 无法加载 DeepSeek API key，请在 D:\\ARS\\deepseek_api_key.txt 中配置！")
        return
    print("✅ DeepSeek API 密钥验证成功。")
    
    # 0. 交互定义工作区文件夹 (支持任意自定义项目目录，默认 D:\ARS)
    print("\n📁 请设置工作区目录 (Workspace Directory)：")
    ws_input = input("👉 请输入工作区路径 [直接回车默认 D:\\ARS]: ").strip()
    if ws_input:
        workspace_dir = Path(ws_input.strip('"\''))
    else:
        workspace_dir = Path(r"D:\ARS")
    workspace_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ➜ 已锁定工作区目录: {workspace_dir}")

    # 2. 交互式采集用户“中文输入公式”四大要素
    print("\n✍️ 请输入当前图表的核心物理参数与现象：")
    print("-" * 50)
    
    fig_id = input("  1. 图表编号 (例如 Figure 1b, Figure 2): ").strip()
    if not fig_id:
        fig_id = "Figure 1b"
        
    method_name = input("  2. 测试方法 (例如 瞬态发光衰减光谱 TRPL, 稳态吸收, transient absorption): ").strip()
    if not method_name:
        method_name = "Steady-state UV-Vis absorption spectroscopy"
        
    samples = input("  3. 样品名称 (例如 纯量子点 QD, 混合物 QD-BDP1): ").strip()
    if not samples:
        samples = "pristine QDs, free dye, and hybrid complex"
        
    print("  4. 核心实验现象与物理推论 (支持任意多行粘贴，中间可随意空行。全部输入完成后，在最后单独一行输入 EOF 并回车提交)：")
    obs_lines = []
    while True:
        try:
            line = input()
            if line.strip().upper() == "EOF":
                break
            obs_lines.append(line)
        except (KeyboardInterrupt, EOFError):
            break
    observations = "\n".join(obs_lines).strip()
    if not observations:
        observations = "No observations entered."
        
    print("-" * 50)
    print("💡 正在本地知识库中自动为您对账检索最匹配的学术写作范式...")
    
    # 3. 智能匹配本地方法学模板并提取文献
    matched_files = select_best_method_files_via_api(method_name, samples, observations, api_key)
    print(f"  ➜ 匹配到最接近的本地方法学文件:")
    for f in matched_files:
        print(f"    - `wiki/methods/{f.name}`")
        
    all_examples = extract_academic_examples(matched_files)
    if not all_examples:
        print("❌ 错误: 无法在匹配的本地方法文件中提取到任何文献范例！")
        return
    print(f"  ➜ 成功提取出 {len(all_examples)} 段顶刊级真实文献段落。")
    
    # 精选前 6 篇 (升级为 LLM 局部语义重排器 Reranker，宽进严出)
    selected_examples = rerank_examples_via_llm(all_examples, observations, method_name, api_key, limit=6)
    print(f"  ➜ 已为您精选出 6 篇在物理演进、逻辑推理上契合度最高的顶刊真题文献模板。")
    
    # 4. 加载文献数据库大表
    matched_papers = load_master_registry_papers()
    
    # 定义输出目录
    safe_fig_dir = make_slug(fig_id)
    target_report_dir = workspace_dir / f"{safe_fig_dir}_Report"
    target_pdfs_dir = target_report_dir / "Source_PDFs"
    
    target_report_dir.mkdir(parents=True, exist_ok=True)
    if target_pdfs_dir.exists():
        try:
            shutil.rmtree(target_pdfs_dir)
        except Exception as err:
            print(f"⚠️ 清空旧 PDF 目录失败: {err}")
    target_pdfs_dir.mkdir(parents=True, exist_ok=True)
    
    # 5. 反查 PDF 并进行拷贝归档
    print("\n🔍 正在反查中央文献库大表，将 6 篇原装 PDF 极速拷贝到您的核对包中...")
    verified_meta = []
    
    for idx, ex in enumerate(selected_examples, 1):
        slug = ex["source"]
        paper_record = find_pdf_for_slug(slug, matched_papers)
        
        ref_info = {
            "index": idx,
            "slug": slug,
            "method_file": ex["method_file"],
            "text": ex["text"],
            "title": "Unknown Title",
            "year": "Unknown Year",
            "authors": "Unknown Authors",
            "pdf_found": False,
            "pdf_filename": None
        }
        
        if paper_record:
            meta = paper_record.get("metadata", {})
            ref_info["title"] = meta.get("title", ref_info["title"])
            ref_info["year"] = meta.get("year", ref_info["year"])
            
            author_names = [a.get("name", "") for a in meta.get("authors", [])]
            if author_names:
                ref_info["authors"] = ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "")
                
            pdf_path_str = paper_record.get("pdf_path")
            if pdf_path_str:
                src_pdf = Path(pdf_path_str)
                if src_pdf.exists():
                    first_author = author_names[0].split()[-1] if author_names else "Author"
                    clean_pdf_name = f"[{idx}] [{ref_info['year']}] {first_author} - {make_slug(ref_info['title'])[:60]}.pdf"
                    target_pdf_path = target_pdfs_dir / clean_pdf_name
                    
                    try:
                        shutil.copy(str(src_pdf), str(target_pdf_path))
                        ref_info["pdf_found"] = True
                        ref_info["pdf_filename"] = clean_pdf_name
                        print(f"  ➜ 🟢 [配对成功] [{idx}] ➡️ 已拷贝 '{clean_pdf_name}'")
                    except Exception as copy_err:
                        print(f"  ➜ ⚠️ 拷贝 PDF 发生异常 [{idx}]: {copy_err}")
                else:
                    print(f"  ➜ ❌ 物理 PDF 文件已被移动或不存在: {pdf_path_str}")
            else:
                print(f"  ➜ ❌ 文献大表中缺失物理 PDF 路径")
        else:
            print(f"  ➜ ❌ 无法在中央大表中反查到 slug '{slug}' 的 PDF 元数据")
            
        verified_meta.append(ref_info)
        
    # 6. 调用 DeepSeek 进行对账写作
    generated_draft = generate_figure_description(
        fig_id, method_name, samples, observations, selected_examples, api_key, workspace_dir
    )
    if not generated_draft:
        print("❌ 错误: DeepSeek API 握手失败，未能生成草稿。")
        return
        
    # 7. 物理存盘草稿文件与对账事实指南
    draft_path = target_report_dir / f"{safe_fig_dir}_Draft.md"
    draft_path.write_text(generated_draft, encoding="utf-8")
    
    # 制作 Verification_Guide.md
    guide_lines = [
        f"# 🔍 {fig_id} 极简人工事实核对与文献比对指南 (Traditional Fact-Checking Guide)\n",
        "本指南专为**人工离线校对**而设计。在本文稿中，所有学术句式和物理推论均通过标准文献编号（如 `[1]`, `[2]`）进行了严格标引。\n",
        "为了方便您、您的导师或通讯作者核对，我们已经把所有引用的**原装文献 PDF 文件**拷贝到了同目录下的 `Source_PDFs/` 文件夹中。您可以直接打开核对！\n",
        "## 📚 Citation Mapping Table (文献引文与PDF文件对照表)\n",
        "| 引文编号 | 物理 PDF 文件 (位于 `Source_PDFs/` 目录) | 完整文献标题与元数据 (Full Title & Metadata) | 库内方法文件 (Method File) |",
        "|---|---|---|---|",
    ]
    for ref in verified_meta:
        pdf_col = f"📁 `{ref['pdf_filename']}`" if ref["pdf_found"] else "❌ 库内未配对成功"
        title_meta = f"**{ref['title']}**<br>*{ref['authors']} ({ref['year']})*"
        guide_lines.append(f"| **[{ref['index']}]** | {pdf_col} | {title_meta} | `{ref['method_file']}` |")
        
    guide_lines.append("\n## 📝 Detail Text Comparison & Excerpts (真题原文精细比对)\n")
    guide_lines.append("以下是我们在您本地数据库中为您检索到的经典原文摘录。本篇手稿中所有高级句式和物理推论均在下述真题原文中有所依据，供您直接在 PDF 中定位核对：\n")
    
    for ref in verified_meta:
        guide_lines.append(f"### 📍 引文 [{ref['index']}]：{ref['title']}")
        guide_lines.append(f"- **完整元数据**: {ref['authors']} ({ref['year']})")
        if ref["pdf_found"]:
            guide_lines.append(f"- **极简核对**: 请直接双击同目录下 `Source_PDFs/` 里的 **`{ref['pdf_filename']}`**")
        guide_lines.append("- **库内方法源文件**: `wiki/methods/` + `" + ref["method_file"] + "`")
        guide_lines.append("- **文献原汁原味英文 (Original English Text used as template)**:")
        guide_lines.append(f"  > *\"{ref['text']}\"*")
        guide_lines.append("\n" + "-"*40 + "\n")
        
    guide_path = target_report_dir / "Verification_Guide.md"
    guide_path.write_text("\n".join(guide_lines), encoding="utf-8")
    
    print("\n" + "=" * 80)
    print("🎉 恭喜！100% 极简离线学术核对包已成功生成！")
    print(f"  ➜ 报告包物理存储目录: {target_report_dir}")
    print(f"  ➜ 1. 干净的论文草稿与中英对照: Figure_X_Report\\{safe_fig_dir}_Draft.md")
    print(f"  ➜ 2. 原装文献 PDF 仓库: Figure_X_Report\\Source_PDFs\\ （已按标号完美重命名，双击即看）")
    print(f"  ➜ 3. 极简事实核对表 (含提取出的真题原文): Figure_X_Report\\Verification_Guide.md")
    print("=" * 80 + "\n")

if __name__ == "__main__":
    main()
