"""Trend report generation utilities

从 trend_data 加载最近文章，构造 prompt，调用 backend.llm.safe_structured 输出 TrendReportSpec
"""
from __future__ import annotations

import textwrap
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend import trend_data, llm as llm_utils

# Import search module for llm_pick_urls (URL scoring)
try:
    from backend.trend_radar_search import search as trend_search
    HAS_TREND_SEARCH = True
except ImportError:
    HAS_TREND_SEARCH = False
    print("[trend_report] Warning: trend_radar_search.search not available, URL scoring disabled")

# ========== 三阶段生成系统 ==========

# 阶段1: 生成方向
_STAGE1_DIRECTIONS_PROMPT = textwrap.dedent(
    """
    You are an AI trend analyst specializing in emerging technology trends and talent identification.

    Based on the recent articles from the past {days} days, please identify the 5 most significant AI/technology directions. Each article entry includes the title and first 500 characters of content to help you understand the technical details and context.

    ## Recent Articles (Past {days} Days):
    Format: Source | Date | Title | Content Preview (500 chars) | URL
    {article_lines}

    ## Task Requirements:
    
    **CRITICAL**: Generate directions that are specific and actionable for talent search. Focus on concrete technical areas where we can identify and recruit key researchers, engineers, and specialists.

    Please structure your response EXACTLY as follows:

    ## A. Directions

    For each of the 5 most significant trends, provide:

    ### 1. **[Direction Name]**
    
    [Provide a detailed 2-3 sentence introduction explaining what this direction is about, why it's important, and its potential impact. This should give readers a comprehensive understanding of the direction before diving into specific projects.]

    **Representative projects**:
    - **[Project Name]**: [Detailed description with key innovations, technical details, and significance]
    - **[Project Name]**: [Detailed description with key innovations, technical details, and significance]
    - **[Project Name]**: [Detailed description with key innovations, technical details, and significance]

    **References**:  
    [List relevant article URLs from the provided articles]

    ---

    [Continue for all 5 directions...]

    ## Important Guidelines:
    1. **Direction Introduction**: Write detailed 2-3 sentence introductions that explain the significance, current developments, and future potential of each direction
    2. **Representative Projects**: Provide comprehensive descriptions including technical details, innovations, and business impact
    3. **Talent-Focused**: Prioritize directions where specific technical skills, research areas, and expertise can be clearly identified for recruiting purposes
    4. **Content-Driven Analysis**: Use the article content previews to identify specific technologies, methodologies, and research areas mentioned in the articles
    5. **Actionable Content**: Focus on trends that organizations can pursue and implement with the right talent
    6. **Evidence-Based**: Ensure all content is based on the provided articles with proper references, utilizing both titles and content previews
    7. **Technical Precision**: Extract specific technical terms, frameworks, and methodologies from article content to create precise direction descriptions
    8. **Professional Tone**: Write for technical and business audiences who need comprehensive understanding
    9. **Format Consistency**: Use the exact format specified above including the ### numbering for directions
    10. **LANGUAGE REQUIREMENT**: Write ALL content in English ONLY. Do not use any Chinese characters or other languages.
    """
)

# Stage 2: Generate talent for each direction
# Stage 2: Generate talent names for network search
_STAGE2_NAME_GENERATION_PROMPT = textwrap.dedent(
    """
    You are an AI talent hunter specializing in identifying recruitable researchers and engineers.

    Based on the direction "{direction_name}" and the related articles (with content previews), identify up to 2 promising talent names who are:
    - Currently working in this field
    - Mentioned or referenced in the articles, OR known researchers in this area  
    - At a recruitable level (PhD students, postdocs, research engineers, junior researchers)
    - NOT famous executives, founders, or well-known leaders like Elon Musk, Geoffrey Hinton, etc.

    ## Direction Details:
    {direction_content}

    ## Related Articles:
    Format: Source | Date | Title | Content Preview (500 chars) | URL
    {article_lines}

    ## Task Requirements:

    Please return 1-2 researcher names in this exact format (one name per line):
    [First Name] [Last Name]
    [First Name] [Last Name]

    Example response:
    Ashish Vaswani
    Jakob Uszkoreit

    ## Important Guidelines:
    1. Focus on RECRUITABLE talent (avoid famous leaders like Yann LeCun, Geoffrey Hinton, etc.)
    2. Prioritize candidates mentioned in the provided articles' content previews, but if none are suitable, use your knowledge of promising researchers in this field
    3. Choose early-career researchers who are making concrete contributions in the field
    4. Return 1-2 names maximum, one per line, no additional formatting or numbering
    5. If you can only find 1 suitable candidate, return just 1 name
    6. **LANGUAGE REQUIREMENT**: Write ALL content in English ONLY. Do not use any Chinese characters or other languages.
    """
)

# Stage 3: Generate detailed report
_STAGE3_DETAILED_REPORT_PROMPT = textwrap.dedent(
    """
    You are an AI report writer specializing in comprehensive trend analysis.

    Based on the direction "{direction_name}" and related articles (with content previews), create a detailed report section.

    ## Direction Details:
    {direction_content}

    ## Related Articles:
    Format: Source | Date | Title | Content Preview (500 chars) | URL
    {article_lines}

    ## Task Requirements:

    Create a comprehensive detailed report covering:

    ### Background
    [80-120 words describing the field and why it matters]

    ### Recent Progress
    - [Notable project/paper 1 with details]
    - [Notable project/paper 2 with details]
    - [Notable project/paper 3 with details]
    - [Notable project/paper 4 with details]

    ### Future Trends & Challenges
    - [Emerging direction 1]
    - [Emerging direction 2]
    - [Open challenge 1]
    - [Open challenge 2]

    ### Actionable Insights
    - [Concrete recommendation 1 for R&D teams]
    - [Concrete recommendation 2 for talent acquisition]
    - [Concrete recommendation 3 for strategic planning]

    ### References
    [List all cited resources with inline Markdown links]

    ## Important Guidelines:
    1. Base all content on the provided articles, utilizing both titles and content previews for comprehensive analysis
    2. Provide actionable insights for organizations
    3. Include specific references and links
    4. Keep background concise but informative
    5. Focus on practical applications and opportunities
    6. **LANGUAGE REQUIREMENT**: Write ALL content in English ONLY. Do not use any Chinese characters or other languages.
    """
)


def _build_article_lines(recent_map: Dict[str, List[Dict]]) -> str:
    """Format article information for LLM consumption with content preview"""
    lines: List[str] = []
    for src, items in recent_map.items():
        for art in items:
            date_str = art.get("parsed_date")
            if date_str:
                date_str = date_str.strftime("%Y-%m-%d")
            else:
                date_str = str(art.get("date", ""))[:10]
            title = art.get("title", "").replace("\n", " ")
            url = art.get("url", "")
            
            # Extract first 500 characters of content
            content = art.get("content", "")
            content_preview = content[:500].replace("\n", " ").strip()
            if len(content) > 500:
                content_preview += "..."
            
            lines.append(f"{src} | {date_str} | {title} | {content_preview} | {url}")
    return "\n".join(lines)


def _clean_unicode_for_api(text) -> str:
    """Clean Unicode characters from text to prevent API encoding errors."""
    if not text:
        return text
    
    # 安全转换为字符串，处理可能的列表、字典等类型
    if not isinstance(text, str):
        if isinstance(text, (list, tuple)):
            # 如果是列表或元组，连接为字符串
            text = ' '.join(str(item) for item in text)
        else:
            # 其他类型直接转换为字符串
            text = str(text)
    
    # Replace common Unicode characters with ASCII equivalents
    replacements = {
        '←': '<-', '→': '->', '↑': '^', '↓': 'v',
        '✓': 'v', '✗': 'x', '★': '*', '☆': '*',
        '•': '*', '◦': '-', '‣': '*',
        '"': '"', '"': '"', ''': "'", ''': "'",
        '—': '-', '–': '-', '…': '...',
        '®': '(R)', '©': '(C)', '™': '(TM)',
    }
    
    # Apply replacements
    for unicode_char, ascii_char in replacements.items():
        text = text.replace(unicode_char, ascii_char)
    
    # Keep only ASCII characters and common whitespace
    # This preserves Chinese/other non-ASCII but converts them to ? or removes them
    # For a more aggressive approach, uncomment the line below:
    # text = ''.join(c if ord(c) < 127 else '?' for c in text)
    
    # Less aggressive: only remove problematic control characters
    text = ''.join(c for c in text if ord(c) >= 32 or c in '\n\t\r')
    
    return text


def label_articles_by_direction(directions: List[str], articles: List[Dict], api_key: str = None) -> Dict[str, List[Dict]]:
    """
    使用LLM给每篇文章分配到5个方向之一
    
    Args:
        directions: 方向名称列表，如 ['Multimodal LLM', 'Edge AI', ...]
        articles: 文章列表，每篇文章包含 title, content, url 等字段
        api_key: LLM API key
        
    Returns:
        {direction_name: [article, ...], 'OTHER': [...]}
    """
    print(f"[label_articles] Starting to label {len(articles)} articles into {len(directions)} directions")
    
    llm_inst = llm_utils.get_llm("dir_label", temperature=0.1, api_key=api_key)
    
    # 初始化标签映射
    label_map = {d: [] for d in directions}
    label_map["OTHER"] = []
    
    # 并发处理文章标签
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def label_single_article(art, idx):
        """为单篇文章打标签"""
        try:
            title = art.get('title', '')[:120]
            content = art.get('content', '')[:400]
            
            # 清理文本
            title = _clean_unicode_for_api(title)
            content = _clean_unicode_for_api(content)
            
            prompt = f"""Known direction list (5 directions):
{', '.join(directions)}

Article Title: {title}
Content Excerpt: {content}

Please return ONLY the most relevant direction name from the list above.
If none match well, return: OTHER

Output only one direction name, no explanation:"""
            
            resp = llm_inst.invoke(prompt, enable_thinking=False)
            from backend.llm import safe_get
            label = (safe_get(resp, "content", "") or safe_get(resp, "text", "") or str(resp)).strip()
            
            # 验证标签是否在列表中
            if label not in label_map:
                # 尝试模糊匹配
                label_lower = label.lower()
                matched = False
                for d in directions:
                    if d.lower() in label_lower or label_lower in d.lower():
                        label = d
                        matched = True
                        break
                if not matched:
                    label = "OTHER"
            
            if idx % 10 == 0:
                print(f"[label_articles] Progress: {idx}/{len(articles)} - '{title[:40]}...' -> {label}")
            
            return art, label
            
        except Exception as e:
            print(f"[label_articles] Error labeling article {idx}: {e}")
            return art, "OTHER"
    
    # 使用线程池并发处理
    max_workers = min(10, len(articles))  # 限制并发数避免API限流
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_idx = {
            executor.submit(label_single_article, art, idx): idx
            for idx, art in enumerate(articles)
        }
        
        for future in as_completed(future_to_idx):
            try:
                art, label = future.result()
                label_map[label].append(art)
            except Exception as e:
                print(f"[label_articles] Future execution error: {e}")
    
    # 输出统计信息
    print(f"\n[label_articles] Labeling completed:")
    for dir_name, arts in label_map.items():
        if arts:  # 只显示非空的方向
            print(f"  - {dir_name}: {len(arts)} articles")
    print()
    
    return label_map


def pick_high_score_refs(dir_name: str, art_list: List[Dict], api_key: str = None, score_threshold: int = 9) -> List[str]:
    """
    使用LLM对方向内的URL打分，返回≥score_threshold分的高质量reference
    
    Args:
        dir_name: 方向名称
        art_list: 该方向下的文章列表
        api_key: LLM API key
        score_threshold: 分数阈值（默认9分）
        
    Returns:
        高分URL列表
    """
    if not HAS_TREND_SEARCH:
        print(f"[pick_high_score_refs] trend_search module not available, returning all URLs")
        return [a["url"] for a in art_list if a.get("url", "").startswith("http")]
    
    if not art_list:
        print(f"[pick_high_score_refs] No articles for direction: {dir_name}")
        return []
    
    print(f"[pick_high_score_refs] Scoring {len(art_list)} articles for direction: {dir_name}")
    
    # 把文章转成SERP格式（llm_pick_urls需要的格式）
    serp = []
    for a in art_list:
        url = a.get("url", "")
        if not url.startswith("http"):
            continue
        serp.append({
            "url": url,
            "title": a.get("title", ""),
            "snippet": a.get("content", "")[:300]  # 取前300字作为snippet
        })
    
    if not serp:
        print(f"[pick_high_score_refs] No valid URLs found for direction: {dir_name}")
        return []
    
    try:
        llm_inst = llm_utils.get_llm("url_score", temperature=0.1, api_key=api_key)
        
        # 调用llm_pick_urls进行打分
        scored = trend_search.llm_pick_urls(
            serp=serp,
            user_query=dir_name,           # 用方向名作为查询上下文
            llm=llm_inst,
            need=len(serp),                # 不限数量，全部打分
            max_per_domain=20              # 每个域名最多20个
        )
        
        # 筛选≥threshold分的URL
        high_score_urls = [url for url, score in scored if score >= score_threshold]
        
        print(f"[pick_high_score_refs] Direction '{dir_name}': {len(high_score_urls)}/{len(serp)} URLs scored ≥{score_threshold}")
        
        # 如果高分URL太少，降低阈值
        if len(high_score_urls) < 3 and score_threshold > 7:
            fallback_threshold = score_threshold - 1
            high_score_urls = [url for url, score in scored if score >= fallback_threshold]
            print(f"[pick_high_score_refs] Lowered threshold to {fallback_threshold}: {len(high_score_urls)} URLs")
        
        return high_score_urls
        
    except Exception as e:
        print(f"[pick_high_score_refs] Error scoring URLs for '{dir_name}': {e}")
        # 失败时返回所有URL
        return [item["url"] for item in serp]


def generate_stage1_directions(days: int = 7, query: str = "", api_key: str = None, include_international: bool = False, international_only: bool = False, data_snapshot: dict = None) -> str:
    """Stage 1: Generate AI trend directions with high-quality reference filtering
    
    新流程：
    1. LLM生成5个方向的初始内容
    2. 解析出方向名称
    3. 给所有文章打标签，分配到5个方向
    4. 对每个方向的URL用LLM打分，筛选≥9分的高质量reference
    5. 重新构造Markdown，包含高分reference列表
    
    Args:
        days: 查询天数
        query: 用户自定义查询
        api_key: LLM API key
        include_international: 是否包含国际源
        international_only: 是否只用国际源
        data_snapshot: 如果提供，则使用这份数据而不是重新爬取
    """
    try:
        # 如果提供了数据快照，使用它；否则爬取新数据
        if data_snapshot is not None:
            print("[trend_report] Stage 1: Using provided data snapshot")
            recent_map = data_snapshot
            print(f"[trend_report] Data snapshot type: {type(recent_map)}")
        else:
            print("[trend_report] Stage 1: Fetching fresh data")
            recent_map = trend_data.query_recent_articles(days=days, include_international=include_international, international_only=international_only)
        
        # ========== 步骤1: LLM生成初始方向内容 ==========
        print("[trend_report] Step 1: Generating initial directions with LLM...")
        article_lines = _build_article_lines(recent_map)
        article_lines = _clean_unicode_for_api(article_lines)

        days_str = str(days) if days else "7"
        article_lines_str = str(article_lines) if article_lines else ""
        
        prompt = _STAGE1_DIRECTIONS_PROMPT.format(days=days_str, article_lines=article_lines_str)

        if not isinstance(query, str):
            query = str(query) if query else ""
            
        if query.strip():
            clean_query = _clean_unicode_for_api(query.strip())
            prompt += f"\n\nUser additional requirements:\n{clean_query}\n"

        prompt = _clean_unicode_for_api(prompt)

        llm = llm_utils.get_llm(role="trend_report", temperature=0.3, api_key=api_key)
        try:
            resp = llm.invoke(prompt, enable_thinking=False)
            from backend.llm import safe_get
            initial_content = safe_get(resp, "content", "") or safe_get(resp, "text", "") or str(resp)
            
            if not isinstance(initial_content, str):
                if isinstance(initial_content, list) and len(initial_content) > 0:
                    if isinstance(initial_content[0], dict) and 'text' in initial_content[0]:
                        initial_content = initial_content[0]['text']
                    else:
                        initial_content = ' '.join(str(item) for item in initial_content)
                else:
                    initial_content = str(initial_content) if initial_content else "# Stage 1 Generation Failed\n\nNo valid response from LLM"
            
        except Exception as llm_error:
            print(f"[trend_report] LLM invocation error in Stage 1: {llm_error}")
            return f"# Stage 1 Generation Failed\n\nLLM Error: {llm_error}"
        
        # ========== 步骤2: 解析方向名称 ==========
        print("[trend_report] Step 2: Parsing direction names...")
        import re
        direction_patterns = [
            re.compile(r'^###\s+(\d+)\.\s+\*\*(.+?)\*\*', re.MULTILINE),
            re.compile(r'^###\s+(\d+)\.\s+(.+)$', re.MULTILINE),
            re.compile(r'^\s*(\d+)\.\s+\*\*(.+?)\*\*', re.MULTILINE),
        ]
        
        direction_names = []
        direction_contents = {}
        
        for pattern in direction_patterns:
            matches = list(pattern.finditer(initial_content))
            if matches and len(matches) >= 3:  # 至少找到3个方向
                for match in matches[:5]:  # 最多5个
                    dir_name = match.group(2).strip()
                    dir_name = re.sub(r'\*\*(.*?)\*\*', r'\1', dir_name)
                    dir_name = re.sub(r'\*(.*?)\*', r'\1', dir_name)
                    dir_name = dir_name.strip()
                    
                    # 提取该方向的完整内容
                    start = match.start()
                    # 找到下一个方向的开始位置
                    next_idx = matches.index(match) + 1
                    if next_idx < len(matches):
                        end = matches[next_idx].start()
                    else:
                        end = len(initial_content)
                    
                    dir_content = initial_content[start:end].strip()
                    
                    direction_names.append(dir_name)
                    direction_contents[dir_name] = dir_content
                    
                print(f"[trend_report] Found {len(direction_names)} directions: {direction_names}")
                break
        
        if not direction_names:
            print("[trend_report] Warning: Could not parse direction names, returning initial content")
            return initial_content
        
        # ========== 步骤3: 收集所有文章并打标签 ==========
        print("[trend_report] Step 3: Labeling articles by direction...")
        all_articles = []
        for source, arts in recent_map.items():
            all_articles.extend(arts)
        
        print(f"[trend_report] Total articles to label: {len(all_articles)}")
        
        # 给文章打标签
        label_map = label_articles_by_direction(direction_names, all_articles, api_key)
        
        # ========== 步骤4: 对每个方向的URL打分，筛选高质量reference ==========
        print("[trend_report] Step 4: Scoring URLs and filtering high-quality references...")
        direction_refs = {}
        
        for dir_name in direction_names:
            arts = label_map.get(dir_name, [])
            high_score_urls = pick_high_score_refs(dir_name, arts, api_key, score_threshold=9)
            direction_refs[dir_name] = high_score_urls
        
        # ========== 步骤5: 重新构造Markdown，插入高分reference ==========
        print("[trend_report] Step 5: Reconstructing Markdown with high-quality references...")
        
        final_markdown_parts = ["## A. Directions\n"]
        
        for idx, dir_name in enumerate(direction_names, 1):
            dir_content = direction_contents.get(dir_name, "")
            high_refs = direction_refs.get(dir_name, [])
            
            # 找到原始内容中的References部分，用高分URL替换
            # 移除原有的References部分
            ref_pattern = re.compile(r'\*\*References\*\*:.*?(?=\n\n---|\n\n###|\Z)', re.DOTALL)
            dir_content_no_refs = ref_pattern.sub('', dir_content).strip()
            
            # 添加新的高分References
            ref_section = f"\n\n**References** 🔗:\n"
            if high_refs:
                for url in high_refs[:15]:  # 最多显示15个
                    ref_section += f"- {url}\n"
                if len(high_refs) > 15:
                    ref_section += f"\n<details>\n<summary>📚 More {len(high_refs)-15} references</summary>\n\n"
                    for url in high_refs[15:]:
                        ref_section += f"- {url}\n"
                    ref_section += "\n</details>\n"
            else:
                ref_section += "- No high-quality references found\n"
            
            # 组装方向内容
            final_markdown_parts.append(f"{dir_content_no_refs}\n{ref_section}\n\n---\n")
        
        final_markdown = "\n".join(final_markdown_parts)
        
        print(f"[trend_report] Stage 1 completed with reference filtering")
        return final_markdown
        
    except Exception as e:
        print(f"[trend_report] Stage 1 error: {e}")
        import traceback
        traceback.print_exc()
        return f"# Stage 1 Generation Failed\n\nError: {e}"

def generate_stage2_talents(direction_name: str, direction_content: str, days: int = 7, api_key: str = None, include_international: bool = False, international_only: bool = False, data_snapshot: dict = None) -> str:
    """Stage 2: Mixed talent search - 1 LLM generated + 1 direction search (total 2 talents)"""
    try:
        # Step 1: Generate a talent name using LLM
        # 如果提供了数据快照，使用它；否则爬取新数据
        if data_snapshot is not None:
            print("[trend_report] Stage 2: Using provided data snapshot")
            recent_map = data_snapshot
        else:
            print("[trend_report] Stage 2: Fetching fresh data")
            recent_map = trend_data.query_recent_articles(days=days, include_international=include_international, international_only=international_only)
        
        article_lines = _build_article_lines(recent_map)
        
        # Clean Unicode characters
        article_lines = _clean_unicode_for_api(article_lines)
        direction_name_clean = _clean_unicode_for_api(direction_name)
        direction_content_clean = _clean_unicode_for_api(direction_content)

        prompt = _STAGE2_NAME_GENERATION_PROMPT.format(
            direction_name=direction_name_clean,
            direction_content=direction_content_clean,
            article_lines=article_lines
        )

        # Clean the entire prompt as final safeguard
        prompt = _clean_unicode_for_api(prompt)

        # 显式传递 api_key
        llm = llm_utils.get_llm(role="trend_report", temperature=0.4, api_key=api_key)
        try:
            resp = llm.invoke(prompt, enable_thinking=False)
            # 使用safe_get来安全获取内容
            from backend.llm import safe_get
            content = safe_get(resp, "content", "") or safe_get(resp, "text", "") or str(resp)
            
            # 确保返回的内容是字符串类型（Stage 2）
            if not isinstance(content, str):
                if isinstance(content, list) and len(content) > 0:
                    if isinstance(content[0], dict) and 'text' in content[0]:
                        content = content[0]['text']
                    else:
                        content = ' '.join(str(item) for item in content)
                else:
                    content = str(content) if content else ""
            
            generated_text = content.strip()
        except Exception as llm_error:
            print(f"[trend_report] LLM invocation error in Stage 2: {llm_error}")
            generated_text = ""
        
        # 解析多个姓名 (支持1-2个姓名，每行一个)
        generated_names = []
        if generated_text and generated_text.strip():
            # 按行拆分，获取每一行的姓名
            lines = generated_text.strip().split('\n')
            
            for line in lines:
                # 清理每行的姓名
                clean_name = line.strip()
                
                # 跳过空行
                if not clean_name:
                    continue
                
                # 移除可能的格式标记和编号
                if ':' in clean_name:
                    clean_name = clean_name.split(':', 1)[-1].strip()
                
                # 移除可能的编号（1. 2. 等）
                import re
                clean_name = re.sub(r'^\d+[\.\)]\s*', '', clean_name).strip()
                
                # 移除markdown格式
                clean_name = re.sub(r'\*\*(.*?)\*\*', r'\1', clean_name)
                clean_name = re.sub(r'\*(.*?)\*', r'\1', clean_name)
                
                # 验证是否看起来像姓名 (至少两个单词，都是字母)
                words = clean_name.split()
                if len(words) >= 2 and len(words) <= 4:  # 姓名通常2-4个词
                    if all(word.replace('-', '').replace('.', '').isalpha() for word in words):
                        generated_names.append(clean_name)
                        if len(generated_names) >= 2:  # 最多2个姓名
                            break
        
        # 调试信息
        if not generated_names:
            print(f"[Stage 2] LLM返回无效姓名格式: '{generated_text[:200]}'")
        else:
            print(f"[Stage 2] LLM解析到有效姓名: {generated_names}")
        
        print(f"[Stage 2] LLM generated {len(generated_names)} names for direction '{direction_name}': {generated_names}")
        
        # Step 2: 多策略人才搜索系统
        try:
            from backend import trend_talent_search
            
            talents_found = []
            
            print(f"[Stage 2] 启动多策略搜索 - 目标方向: {direction_name}")
            
            # 🎯 两层收集 + 优中选优机制
            TARGET_TALENTS = 5  # 每个方向最终输出5个人才
            MIN_TALENTS = 1     # 最少1个人才
            TARGET_TWEET_TALENTS = 2  # 推文固定获取2个
            TARGET_DIRECTION_TALENTS = 3  # 方向固定搜索5个
            
            talents_from_tweets = []  # 推文获取的人才
            talents_from_direction = []  # 方向搜索的人才
            
            # ========== 第一层：推文姓名搜索（固定2个）==========
            if generated_names:
                print(f"[Stage 2] 第一层：推文姓名搜索 - 固定获取 {TARGET_TWEET_TALENTS} 个")
                name_search_results = trend_talent_search.search_talents_by_names(
                    names=generated_names,  
                    max_per_name=TARGET_TWEET_TALENTS,
                    api_key=api_key
                )
                if name_search_results:
                    talents_from_tweets = name_search_results[:TARGET_TWEET_TALENTS]
                    talents_found.extend(talents_from_tweets)
                    for talent in talents_from_tweets:
                        print(f"[Stage 2]   ✅ 推文: {talent.get('title', '未知')} (评分: {talent.get('total_score', 0)}/35)")
                else:
                    print(f"[Stage 2]   ❌ 推文获取失败")
            else:
                print(f"[Stage 2] 第一层：跳过（LLM未生成姓名）")
            
            print(f"[Stage 2] 第一层完成: {len(talents_from_tweets)} 个人才")
            
            # ========== 第二层：方向搜索（固定3个）==========
            print(f"[Stage 2] 第二层：方向搜索 - 固定搜索 {TARGET_DIRECTION_TALENTS} 个")
            
            direction_search_results = trend_talent_search.search_talents_for_direction(
                direction_title=direction_name,
                direction_content=direction_content, 
                max_candidates=TARGET_DIRECTION_TALENTS,  # 固定搜索3个
                api_key=api_key
            )
            
            if direction_search_results:
                # 去重：排除已在推文中找到的人才
                existing_names = {t.get('title', '').lower().strip() for t in talents_found}
                for talent in direction_search_results:
                    talent_name = talent.get('title', '').lower().strip()
                    if talent_name not in existing_names and len(talent_name) > 2:
                        talents_from_direction.append(talent)
                        talents_found.append(talent)
                        existing_names.add(talent_name)
                        print(f"[Stage 2]   ✅ 方向: {talent.get('title', '未知')} (评分: {talent.get('total_score', 0)}/35)")
                
                print(f"[Stage 2] 第二层完成: {len(talents_from_direction)} 个新人才")
            else:
                print(f"[Stage 2] 第二层失败: 无结果")
            
            # ========== 优中选优：按评分排序取top 5 ==========
            print(f"[Stage 2] 候选池总计: {len(talents_found)} 个人才")
            
            # 按 total_score 降序排序
            talents_found.sort(key=lambda t: t.get('total_score', 0), reverse=True)
            
            # 取评分最高的前5个
            talents_found = talents_found[:TARGET_TALENTS]
            
            print(f"[Stage 2] 优中选优: 从 {len(talents_from_tweets) + len(talents_from_direction)} 人中选出评分最高的 {len(talents_found)} 人")
            for i, t in enumerate(talents_found, 1):
                print(f"  {i}. {t.get('title', '未知')}: {t.get('total_score', 0)}/35")
            
            # ========== 搜索总结 ==========
            print(f"[Stage 2] 两层机制完成:")
            print(f"  第一层（推文姓名）: {len(talents_from_tweets)} 人")
            print(f"  第二层（方向搜索）: {len(talents_from_direction)} 人")
            print(f"  总计: {len(talents_found)} 人")
            
            # Format the results
            if len(talents_found) >= MIN_TALENTS:
                markdown_text = _format_talents_for_stage2(direction_name, talents_found)
                return {
                    'markdown': markdown_text,
                    'structured_data': talents_found
                }
            else:
                print(f"[Stage 2] 人才数量不足最低要求 ({len(talents_found)} < {MIN_TALENTS})")
                return {
                    'markdown': f"### {direction_name}\n\n*Failed to find minimum required talents ({len(talents_found)}/{MIN_TALENTS}). Please try again later.*",
                    'structured_data': []
                }
        
        except ImportError as ie:
            print(f"[Stage 2] Talent search module not available: {ie}")
            return {
                'markdown': f"### {direction_name}\n\n*Talent search functionality unavailable: {ie}*",
                'structured_data': []
            }
        except Exception as search_error:
            print(f"[Stage 2] Network search error: {search_error}")
            return {
                'markdown': f"### {direction_name}\n\n*Network search failed: {search_error}*",
                'structured_data': []
            }
        
    except Exception as e:
        print(f"[trend_report] Stage 2 error for direction '{direction_name}': {e}")
        return {
            'markdown': f"### {direction_name}\n\n*Talent generation failed: {e}*",
            'structured_data': []
        }


def _format_talents_for_stage2(direction_name: str, talents: list) -> str:
    """Format network-searched talents into the expected Stage 2 output format"""
    if not talents:
        return f"### {direction_name}\n\n*No talents found.*"
    
    result = f"### {direction_name}\n\n"
    
    for i, talent in enumerate(talents, 1):
        name = talent.get('title', 'Unknown Researcher')
        affiliation = talent.get('affiliation', talent.get('current_role_affiliation', 'Unknown Institution'))
        research_focus = talent.get('research_focus', [])
        highlights = talent.get('highlights', [])
        
        # Format research focus
        research_desc = ', '.join(research_focus[:3]) if research_focus else 'Research focus not specified'
        
        # Get notable contribution from highlights or research focus
        notable_contribution = highlights[0] if highlights else research_desc
        if len(notable_contribution) > 200:
            notable_contribution = notable_contribution[:200] + "..."
            
        # Determine role from affiliation or default
        role = "Researcher"  # Default
        if "PhD" in affiliation:
            role = "PhD Student"
        elif "Postdoc" in affiliation:
            role = "Postdoc"
        elif "Professor" in affiliation:
            role = "Research Scientist"
        
        result += f"""#### {i}.1 {name}
**Affiliation**: {affiliation}
**Role**: {role}
**Research Focus**: {research_desc}
**Notable Contribution**: {notable_contribution}
**Contact Potential**: Early-career researcher with strong publication record
**Source**: Network Search

"""
    
    return result

def generate_stage3_detailed_report(direction_name: str, direction_content: str, days: int = 7, api_key: str = None, include_international: bool = False, international_only: bool = False, data_snapshot: dict = None) -> str:
    """Stage 3: Generate detailed report for each direction"""
    try:
        # 如果提供了数据快照，使用它；否则爬取新数据
        if data_snapshot is not None:
            print("[trend_report] Stage 3: Using provided data snapshot")
            recent_map = data_snapshot
        else:
            print("[trend_report] Stage 3: Fetching fresh data")
            recent_map = trend_data.query_recent_articles(days=days, include_international=include_international, international_only=international_only)
        
        article_lines = _build_article_lines(recent_map)
        
        # Clean Unicode characters
        article_lines = _clean_unicode_for_api(article_lines)
        direction_name = _clean_unicode_for_api(direction_name)
        direction_content = _clean_unicode_for_api(direction_content)

        prompt = _STAGE3_DETAILED_REPORT_PROMPT.format(
            direction_name=direction_name,
            direction_content=direction_content,
            article_lines=article_lines
        )

        # Clean the entire prompt as final safeguard
        prompt = _clean_unicode_for_api(prompt)

        # 传递 api_key 以支持多线程环境（ThreadPoolExecutor 无法访问 session_state）
        llm = llm_utils.get_llm(role="trend_detail", temperature=0.3, api_key=api_key)
        try:
            resp = llm.invoke(prompt, enable_thinking=False)
            # 使用safe_get来安全获取内容
            from backend.llm import safe_get
            content = safe_get(resp, "content", "") or safe_get(resp, "text", "") or str(resp)
            
            # 确保返回的内容是字符串类型（Stage 3）
            if not isinstance(content, str):
                if isinstance(content, list) and len(content) > 0:
                    if isinstance(content[0], dict) and 'text' in content[0]:
                        content = content[0]['text']
                    else:
                        content = ' '.join(str(item) for item in content)
                else:
                    content = str(content) if content else f"## {direction_name} - Detailed Report\n\nNo valid response from LLM"
            
            return content
        except Exception as llm_error:
            print(f"[trend_report] LLM invocation error in Stage 3: {llm_error}")
            return f"## {direction_name} - Detailed Report\n\nLLM Error: {llm_error}"
        
    except Exception as e:
        print(f"[trend_report] Stage 3 error for direction '{direction_name}': {e}")
        return f"## {direction_name} - Detailed Report\n\n*Detailed report generation failed: {e}*"

def generate_three_stage_report(days: int = 7, query: str = "", progress_callback=None, api_key: str = None, include_international: bool = False, international_only: bool = False, data_snapshot: dict = None) -> Dict[str, str]:
    """Execute complete three-stage generation workflow"""
    result = {
        "stage1_directions": "",
        "stage2_talents": {},
        "stage3_detailed_reports": {},
        "final_report": "",
        "errors": []
    }
    
    try:
        # 预处理：爬取数据快照（只爬取一次）
        if data_snapshot is None:
            print("[trend_report] Fetching data snapshot for entire report...")
            if progress_callback:
                progress_callback(1, 10, "Fetching fresh data...")
            data_snapshot = trend_data.query_recent_articles(days=days, include_international=include_international, international_only=international_only)
            print(f"[trend_report] Data snapshot ready: {sum(len(articles) for articles in data_snapshot.values())} total articles")
        else:
            print("[trend_report] Using provided data snapshot")
        
        # 阶段1: 生成方向
        print("[trend_report] Starting Stage 1: Generating directions...")
        if progress_callback:
            progress_callback(2, 25, "Stage 1: Generating trend directions...")
        stage1_result = generate_stage1_directions(days=days, query=query, api_key=api_key, include_international=include_international, international_only=international_only, data_snapshot=data_snapshot)
        result["stage1_directions"] = stage1_result
        
        # 解析方向 - 修复正则表达式以匹配实际输出格式
        import re
        # 尝试多种可能的方向格式 - 按实际生成的格式优先排序
        direction_patterns = [
            re.compile(r'^###\s+(\d+)\.\s+\*\*(.+?)\*\*', re.MULTILINE),  # ### 1. **方向名称** (实际格式)
            re.compile(r'^###\s+(\d+)\.\s+(.+)$', re.MULTILINE),         # ### 1. 方向名称
            re.compile(r'^\s*(\d+)\.\s+(.+)$', re.MULTILINE),            # 1. 方向名称
            re.compile(r'^\s*(\d+)\.\s+\*\*(.+?)\*\*', re.MULTILINE),     # 1. **方向名称**
            re.compile(r'^\s*(\d+)\)\s+(.+)$', re.MULTILINE),            # 1) 方向名称
        ]
        
        directions = {}
        direction_matches = []
        
        # 尝试不同的模式直到找到匹配
        for pattern in direction_patterns:
            direction_matches = list(pattern.finditer(stage1_result))
            if direction_matches:
                print(f"[trend_report] Using pattern: {pattern.pattern}")
                break
        
        if not direction_matches:
            print(f"[trend_report] Warning: No direction pattern matched. First 500 chars of stage1_result:")
            print(repr(stage1_result[:500]))
        
        for i, match in enumerate(direction_matches):
            dir_num = match.group(1)
            dir_name = match.group(2).strip()
            
            # 清理方向名称中可能的markdown标记
            dir_name = re.sub(r'\*\*(.*?)\*\*', r'\1', dir_name)  # **text** -> text
            dir_name = re.sub(r'\*(.*?)\*', r'\1', dir_name)      # *text* -> text
            
            # 移除可能的尾部markdown标记（如 "### 5." 这样的后缀）
            dir_name = re.sub(r'\s*###\s*\d+\.?\s*$', '', dir_name)  # 移除尾部的 ### 数字
            dir_name = re.sub(r'\s*\d+\.\s*$', '', dir_name)  # 移除尾部的数字
            
            dir_name = dir_name.strip()
            
            print(f"[trend_report] Found direction {dir_num}: '{dir_name}'")
            
            # 提取该方向的内容 (从当前匹配到下一个方向或文件结尾)
            start_pos = match.start()
            next_match = None
            for j, next_m in enumerate(direction_matches):
                if j > i:  # 找到下一个匹配
                    next_match = next_m
                    break
            
            if next_match:
                end_pos = next_match.start()
            else:
                end_pos = len(stage1_result)
            
            dir_content = stage1_result[start_pos:end_pos].strip()
            directions[dir_name] = dir_content
        
        print(f"[trend_report] Found {len(directions)} directions: {list(directions.keys())}")
        
        # 阶段2: 为每个方向生成人才
        print("[trend_report] Starting Stage 2: Generating talents for each direction...")
        if progress_callback:
            progress_callback(2, 60, "Stage 2: Generating recruitable talents for each direction...")
        
        stage2_talents_structured = {}  # 保存结构化人才数据
        for dir_name, dir_content in directions.items():
            print(f"[trend_report] Generating talents for: {dir_name}")
            talents_result = generate_stage2_talents(dir_name, dir_content, days=days, api_key=api_key, include_international=include_international, international_only=international_only, data_snapshot=data_snapshot)
            
            # 处理新的返回格式（字典：markdown + structured_data）
            if isinstance(talents_result, dict):
                result["stage2_talents"][dir_name] = talents_result.get('markdown', '')
                stage2_talents_structured[dir_name] = talents_result.get('structured_data', [])
            else:
                # 向后兼容：如果返回的是字符串（旧格式）
                result["stage2_talents"][dir_name] = talents_result
                stage2_talents_structured[dir_name] = []
        
        # 保存结构化人才数据到结果中
        result["stage2_talents_structured"] = stage2_talents_structured
        
        # 阶段3: 并行生成详细报告
        print("[trend_report] Starting Stage 3: Generating detailed reports (parallel)...")
        if progress_callback:
            progress_callback(3, 80, "Stage 3: Generating detailed reports (parallel)...")

        stage3_reports: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(directions) or 1) as executor:
            future_to_dir = {
                executor.submit(
                    generate_stage3_detailed_report,
                    dir_name,
                    dir_content,
                    days,
                    api_key,
                    include_international,
                    international_only,
                    data_snapshot,
                ): dir_name
                for dir_name, dir_content in directions.items()
            }

            completed = 0
            for future in as_completed(future_to_dir):
                dir_name = future_to_dir[future]
                try:
                    stage3_reports[dir_name] = future.result()
                except Exception as e:
                    stage3_reports[dir_name] = f"## {dir_name} - Detailed Report\n\n*Generation failed: {e}*"
                completed += 1
                print(f"[trend_report] Stage 3 progress: {completed}/{len(directions)} completed")

        result["stage3_detailed_reports"] = stage3_reports
        
        # 组装最终报告 - 格式化为前端期望的结构
        final_report_parts = [stage1_result]
        
        # 添加 Talent 部分
        if result["stage2_talents"]:
            final_report_parts.append("\n\n## B. Talent")
            final_report_parts.append("\n")
            
            # 按direction顺序组装talent内容  
            for idx, (dir_name, talent_content) in enumerate(result["stage2_talents"].items(), 1):
                # 将Stage 2的输出格式转换为前端期望的格式
                # 从 "### Direction Name" 转换为 "### 1) Direction Name"
                formatted_talent = talent_content.replace(f"### {dir_name}", f"### {idx}) {dir_name}")
                final_report_parts.append(formatted_talent)
                final_report_parts.append("\n")
        
        result["final_report"] = "\n".join(final_report_parts)
        
        print("[trend_report] Three-stage generation completed successfully!")
        if progress_callback:
            progress_callback(4, 100, "Three-stage generation completed!")
        return result
        
    except Exception as e:
        print(f"[trend_report] Three-stage generation error: {e}")
        result["errors"].append(str(e))
        return result

# 保持向后兼容的接口
def generate_report(days: int = 7, query: str = "") -> str:
    """Generate markdown Trend Radar report using three-stage approach."""
    try:
        three_stage_result = generate_three_stage_report(days=days, query=query)
        
        if three_stage_result["errors"]:
            print(f"[trend_report] Errors during generation: {three_stage_result['errors']}")
        
        return three_stage_result.get("final_report", "# Report Generation Failed")
        
    except Exception as e:
        print(f"[trend_report] General error: {e}")
        return f"# Trend Report Generation Failed\n\nError: {e}"


if __name__ == "__main__":
    rpt = generate_report(days=7)
    print(rpt)
