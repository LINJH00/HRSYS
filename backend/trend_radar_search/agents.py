"""
Agent functions for Talent Search System
Handles query parsing and search execution
"""

from typing import Dict, Any, List, Tuple, Union, Optional
import json
import sys
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy

# Use robust import utilities
from pathlib import Path
import sys

# Add project paths for imports
current_dir = Path(__file__).parent
backend_dir = current_dir.parent
sys.path.insert(0, str(backend_dir))
sys.path.insert(0, str(current_dir))

try:
    import schemas
    from schemas import (
        QuerySpec,
        ResearchState,
        QuerySpecDiff,
        CandidateOverview,
        EvaluationResult,
        PaperCollection,
        PaperInfo,
        PaperAuthorsResult,
        AuthorWithId,
    )
    import docker_utils
    import search
    from search import score_and_rank_papers_parallel  # Import new scoring function
    import utils
    from backend import config
    from backend import llm
    import extraction
    from author_discovery import AuthorProfile, orchestrate_candidate_report  # type: ignore
    from semantic_paper_search import SemanticScholarClient  # type: ignore
    from dynamic_concurrency import get_optimal_workers, get_candidate_workers, get_extraction_workers, get_llm_workers  # type: ignore
except Exception as e:
    print(f"Agents ImportError: {e}")

def agent_parse_search_query(search_query: str, api_key: str = None) -> QuerySpec:
    """
    Parse a natural language search query into structured QuerySpec

    Args:
        search_query: Natural language query from user
        api_key: Optional API key for LLM calls

    Returns:
        QuerySpec: Structured search parameters
    """
    # 使用LLM解析查询（如果LLM可用）
    try:
        llm_instance = llm.get_llm("parse", temperature=0.3, api_key=api_key)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        # 获取所有研究方向的列表
        research_fields = list(config.CS_TOP_CONFERENCES.keys())
        fields_list = ", ".join(research_fields)
        prompt = (
            "You are a professional talent recruitment analysis assistant responsible for parsing recruitment queries and extracting structured information.\n\n"
            "=== PARSING TASK INSTRUCTIONS ===\n"
            "Please carefully analyze the user's recruitment query and extract the following key information:\n\n"
            "1. **top_n** (int): Number of candidates needed. Look for numbers in the query like '10 candidates', '20 people', etc.\n\n"
            f"2. **years** (int[]): Years to focus on for papers. Default to {config.DEFAULT_YEARS} (last year, this year, next year) if not specified.\n\n"
            "3. **venues** (string[]): Target conferences/journals. Users will explicitly mention venues like 'ACL', 'NeurIPS', etc.\n"
            f"   Known venues include (not exhaustive): {conf_list}\n"
            "   Recognition rules:\n"
            "   - Direct conference names: ACL, EMNLP, NAACL, NeurIPS, ICLR, ICML\n"
            "   - Conference variants: NIPS→NeurIPS, The Web Conference→WWW\n"
            "   - Platforms: OpenReview (counts as a venue)\n\n"
            "4. **keywords** (string[]): Research areas and technical keywords.\n"
            "   CRITICAL EXTRACTION RULES (STRICT):\n"
            "   - Only extract keywords or phrases that appear verbatim (case-insensitive) in the user's query.\n"
            "   - Do NOT infer, expand, or add related technologies, synonyms, acronyms, abbreviations, or parent/child research fields that are NOT explicitly written by the user.\n"
            "   - Multi-word technical phrases MUST be preserved as one single keyword. Example: 'graph foundation model' must stay as one keyword.\n"
            "   - If a multi-word keyword is present, DO NOT also include its sub-components or shorter related forms unless they also appear explicitly in the query.\n"
            "   - If a term is mentioned in a negated context, DO NOT include it as a keyword.\n"
            "     Negation patterns include: 'not X', 'no X', 'without X', 'avoid X', 'exclude X', 'except X', 'rather than X'.\n"
            "   - Do NOT split a phrase into smaller parts. If no keyword exactly matches known terms, return the original phrase exactly as written by the user.\n"
            "   - Do NOT add high-level general fields like 'machine learning', 'deep learning', 'AI', 'artificial intelligence', or 'data science' unless these terms are explicitly written by the user.\n"
            "   - Do NOT normalize, paraphrase, or interpret the user's intent. Only extract exactly what they wrote.\n\n"
            "5. **research_field** (string): Primary research field/direction that best matches the query.\n"
            f"   Available fields: {fields_list}\n"
            "   Recognition rules:\n"
            "   - Analyze the keywords and overall context to identify the PRIMARY research field\n"
            "   - If keywords mention 'robot', 'robotics', 'manipulation', 'navigation' → 'Robotics'\n"
            "   - If keywords mention 'NLP', 'language model', 'translation', 'sentiment' → 'Natural Language Processing'\n"
            "   - If keywords mention 'vision', 'image', 'object detection', 'segmentation' → 'Computer Vision'\n"
            "   - If keywords mention 'deep learning', 'neural network', 'training' → 'Machine Learning'\n"
            "   - If keywords mention 'database', 'SQL', 'query optimization' → 'Databases'\n"
            "   - If keywords mention 'security', 'encryption', 'vulnerability' → 'Computer Security'\n"
            "   - Default to 'Machine Learning' if unclear\n\n"
            "6. **must_be_current_student** (bool): Whether candidates must be current students. Look for:\n"
            "   - Explicit requirements: current student, currently enrolled, active student\n"
            "   - Degree phases: PhD student, Master's student, graduate student\n"
            "   - Default: true (unless explicitly stated otherwise)\n\n"
            "7. **degree_levels** (string[]): Acceptable degree levels.\n"
            "   CRITICAL EXTRACTION RULES (MUST FOLLOW EXACTLY):\n"
            "   - ONLY extract the EXACT degree terms that appear verbatim in the user's query text.\n"
            "   - Recognized degree patterns: \"PhD\", \"PhD student\", \"Doctoral\", \"Master\", \"MSc\", \"MS\",\n"
            "     \"Graduate\", \"Undergraduate\", \"Bachelor\", \"Postdoc\", \"MD\", \"MBA\".\n"
            "   - DO NOT add synonyms, variants, or related degrees that are NOT written in the query.\n"
            "     Examples:\n"
            "     * If query says \"PhD/MSc\" → return [\"PhD\", \"MSc\"] only, NOT [\"PhD\", \"MSc\", \"Master\"]\n"
            "     * If query says \"Master students\" → return [\"Master\"] only, NOT [\"Master\", \"MSc\"]\n"
            "     * If query says \"PhD candidates\" → return [\"PhD\"] only\n"
            "   - If a degree appears in a phrase (e.g. \"PhD student\"), extract the base term (\"PhD\") unless the full phrase is significant.\n"
            "   - If the query includes ANY degree term explicitly, DO NOT add default values.\n"
            "   - If the query does NOT mention any degree information at all, use this default:\n"
            "     [\"PhD\", \"MSc\", \"Master\", \"Graduate\"].\n"
            "   - When in doubt, extract FEWER degrees rather than adding unmentioned ones.\n\n"
            "8. **author_priority** (string[]): Author position preferences.\n"
            "   Recognition: first author, last author, corresponding author\n"
            "   Default: ['first', 'last']\n\n"
            "9. **extra_constraints** (string[]): Other constraints.\n"
            "   Recognition: geographic requirements (e.g., 'Asia', 'North America')\n"
            "   institutional requirements (e.g., 'top universities', 'Ivy League')\n"
            "   language requirements, experience requirements, etc.\n\n"
            "=== PARSING STRATEGY TIPS ===\n"
            "• Prioritize explicitly mentioned information, then make reasonable inferences\n"
            "• For technical keywords, identify specific models, methods, and research areas\n"
            "• Distinguish between different recruitment goals: interns vs researchers vs postdocs\n"
            "• Pay attention to time-sensitive information: recent publications, accepted papers, upcoming deadlines\n\n"
            "Return STRICT JSON format only, no additional text.\n\n"
            "User Query:\n"
            f"{search_query}\n"
        )

        query_spec = llm.safe_structured(llm_instance, prompt, schemas.QuerySpec)

        # 如果venues为空，根据research_field选择对应的会议
        if query_spec.venues == []:
            # 核心会议（固定）
            core_venues = config.CORE_CONFERENCES.copy()
            
            # 根据research_field选择对应方向的会议
            research_field = query_spec.research_field or "Machine Learning"
            field_venues = config.CS_TOP_CONFERENCES.get(research_field, [])
            
            # 如果该方向没有会议，回退到默认
            if not field_venues:
                field_venues = config.TOP_TIER_CONFERENCES.copy()
                print(f"[Parse Query] No conferences found for field '{research_field}', using default pool")
            
            # 合并核心会议和方向会议
            query_spec.venues = core_venues + field_venues
            
            print(f"[Parse Query] No venues specified, using conferences for field '{research_field}':")
            print(f"  Core: {core_venues}")
            print(f"  Field ({research_field}): {field_venues}")
            print(f"  Final: {query_spec.venues}")

        return query_spec

    except Exception as e:
        print(f"LLM解析失败，使用模拟数据: {e}")

        # 回退到模拟数据
        fallback_years = config.DEFAULT_YEARS.copy()
        core_venues = config.CORE_CONFERENCES.copy()
        fallback_field = "Machine Learning"
        field_venues = config.CS_TOP_CONFERENCES.get(fallback_field, [])
        fallback_venues = core_venues + field_venues
        
        print(f"[Fallback] Using default configuration:")
        print(f"  Years: {fallback_years}")
        print(f"  Field: {fallback_field}")
        print(f"  Venues: {fallback_venues}")
        
        return schemas.QuerySpec(
            top_n=10,
            years=fallback_years,
            venues=fallback_venues,
            keywords=["social simulation", "multi-agent systems"],
            research_field=fallback_field,
            must_be_current_student=True,
            degree_levels=["PhD", "Master"],
            author_priority=["first"],
        )


def _plan_terms(spec: QuerySpec) -> List[str]:
    try:
        return search.build_conference_queries(
            spec, config.DEFAULT_CONFERENCES, cap=config.MAX_SEARCH_TERMS
        )
    except Exception:
        return [
            "accepted papers program schedule",
        ]


def _run_search_terms(
    terms: List[str], k_per_query: int = 10) -> List[Dict[str, Any]]:
    """
    Search for papers using Azure AI Agent API.
    
    Args:
        terms: List of search terms/queries
        k_per_query: Number of papers to retrieve per query (default: 10)
    
    Returns:
        List of paper dictionaries with title, authors, abstract, introduction, etc.
    """
    results: List[Dict[str, Any]] = []
    if not terms:
        return results
    try:
        from azure.ai.projects import AIProjectClient 
        from azure.ai.agents.models import ListSortOrder
        from azure.identity import  AzureCliCredential
    except ImportError as e:
        print(f"Azure SDK ImportError: {e}")
    
    try:
        endpoint = getattr(config, "AZURE_AI_PROJECT_ENDPOINT", None)
        agent_name = getattr(config, "AZURE_AI_PROJECT_AGENT_NAME", None)
        
        project = AIProjectClient(
            credential = AzureCliCredential(),
            endpoint = endpoint
        )    
        agent = project.agents.get_agent(agent_name)
        
        for idx, term in enumerate(terms):
            try:
                thread = project.agents.threads.create()
                search_prompt=f"""
                Give me 10 papers focused on ""{term}"",preferably those accepted at ICML,NeurIPS,ICLR,or domain-specific conferences such as ACL,EMNLP
                NAACL for NLP-related topics, or ICCV, ECCV, CVPR for computer vision-related topics,as well as other high-impact papers from arXiv of Google Scholar.
                The papers should also be available on arXiv and please provide their corresponding arXiv links.You must output in json format below:
                [
                    {{
                        "title": "...",
                        "authors": ["...", "..."],
                        "arxiv_link": "...",
                        "abstract": "...",
                        "introduction": "... (first 2-3 paragraphs of the introduction section if available)"
                    }},
                    ...
                ]
                """
                message = project.agents.messages.create(
                    thread_id=thread.id,
                    role="user",
                    content=search_prompt
                )
                run = project.agents.runs.create_and_process(
                    thread_id=thread.id,
                    agent_id=agent.id
                )
                if run.status == "failed":
                    print(f"[agent.search] term error: {term} -> run failed")
                    continue
                messages = project.agents.messages.list(
                    thread_id=thread.id,
                    order=ListSortOrder.ASCENDING
                )
                papers_found = 0
                for msg in messages:
                    if msg.role == "assistant" and msg.text_messages:
                        test_msg = msg.text_messages[0]
                        content = None
                        if hasattr(test_msg, 'text') and hasattr(test_msg.text, 'value'):
                            content = test_msg.text.value
                        elif hasattr(test_msg, 'value'):
                            content = test_msg.value
                        elif hasattr(test_msg, 'text') and isinstance(test_msg.text, str):
                            content = test_msg.text
                        else:
                            content = str(test_msg)
                            if not content or not isinstance(content, str):
                                print(f"[agent.search] term error: {term} -> no valid content")
                                continue
                        try:
                            json_str = content.strip()
                            
                            # Handle markdown code blocks
                            if "```json" in json_str:
                                start = json_str.find("```json") + 7
                                end = json_str.find("```", start)
                                json_str = json_str[start:end].strip()
                            elif "```" in json_str:
                                start = json_str.find("```") + 3
                                end = json_str.find("```", start)
                                json_str = json_str[start:end].strip()
                            
                            if json_str.startswith("json"):
                                json_str = json_str[4:].strip()
                            
                            papers = json.loads(json_str)
                            
                            if not isinstance(papers, list):
                                if isinstance(papers, dict) and 'papers' in papers:
                                    papers = papers['papers']
                                else:
                                    papers = [papers]
                            
                            for paper in papers[:k_per_query]:
                                url = paper.get("arxiv_link", "").strip()
                                title = paper.get("title", "").strip()
                                abstract = paper.get("abstract", "").strip()
                                introduction = paper.get("introduction", "").strip()
                                if not url or not url.startswith("http") or not title:
                                    continue
                                authors_list = paper.get("authors", [])
                                authors_formatted = []
                                for author_name in authors_list:
                                    if isinstance(author_name, str):
                                        authors_formatted.append({"name": author_name})
                                result = {
                                    "url": url,
                                    "title": title,
                                    "authors": authors_formatted,
                                    "snippet": abstract[:500],
                                    "abstract": abstract,  # Keep full abstract
                                    "introduction": introduction,  # Add introduction field
                                    "engine": "azure_ai_agent",
                                    "category": paper,
                                    "term": term,
                                    "parsed_url": url,
                                    "engines": ["azure_aiagent"],
                                    "positions": [len(results) + 1]
                                }
                                
                                results.append(result)
                                papers_found += 1
                        except json.JSONDecodeError as je:
                            print(f"[agent.search] JSON decode error for term '{term}': {je}")
                        except Exception as e:
                            print(f"[agent.search] error processing message for term '{term}': {e}")
                        
                        break
            except Exception as e:
                print(f"[agent.search] term error: {term} -> {e}")
                import traceback
                traceback.print_exc()
                continue
    
    except Exception as e:
        print(f"[agent.search] overall search error: {e}")
        import traceback
        traceback.print_exc()
        return []
    
    # Dedupe by url
    seen = set()
    uniq = []
    for r in results:
        u = r.get("url", "")
        if u and u not in seen:
            seen.add(u)
            uniq.append(r)
    
    return uniq

def classify_role_rule_based(role_text: str) -> str:
    """Rule-based role classification as fallback
    
    Args:
        role_text: The role/position text to classify
    
    Returns:
        One of the 6 role categories or "Unknown"
    """
    if not role_text or not role_text.strip():
        return "Unknown"
    
    t = role_text.lower()
    
    # Define keyword patterns for each category
    # Priority: Check from highest to lowest priority
    
    # 1. Professor (highest priority)
    professor_patterns = [
        "assistant professor", "associate professor", "full professor",
        "asst prof", "assoc prof", "professor", "prof.",
    ]
    if any(p in t for p in professor_patterns):
        # Exclude "former professor", "ex-professor"
        if not any(ex in t for ex in ["former", "ex-", "received", "got my"]):
            return "Professor"
    
    # 2. Postdoc
    postdoc_patterns = [
        "postdoc", "post-doc", "post doc", "postdoctoral", "post-doctoral",
        "postdoctoral researcher", "postdoctoral fellow",
    ]
    if any(p in t for p in postdoc_patterns):
        if not any(ex in t for ex in ["former", "ex-", "received", "completed"]):
            return "Postdoc"
    
    # 3. Industrial Researcher
    # Keywords: company names, "industry", combined with researcher/scientist
    industrial_keywords = [
        "google", "microsoft", "meta", "facebook", "amazon", "apple", 
        "nvidia", "openai", "deepmind", "anthropic", "bytedance", "tencent",
        "baidu", "alibaba", "huawei", "intel", "ibm", "sony",
    ]
    researcher_keywords = [
        "research scientist", "researcher", "research engineer", 
        "senior researcher", "staff researcher", "research intern",
    ]
    
    has_industrial_keyword = any(k in t for k in industrial_keywords) or "industry" in t or "company" in t
    has_researcher_keyword = any(k in t for k in researcher_keywords)
    
    if has_industrial_keyword and has_researcher_keyword:
        return "IndustrialResearcher"
    
    # 4. Institution Researcher (academic institution)
    institution_keywords = [
        "university", "institute", "college", "academia", "research center",
        "research institute", "laboratory", "lab",
    ]
    has_institution_keyword = any(k in t for k in institution_keywords)
    
    if has_institution_keyword and has_researcher_keyword:
        return "InstitutionResearcher"
    
    # If only researcher keyword without clear context, check for PhD mention
    if has_researcher_keyword:
        # If mentions "phd" or "ph.d.", likely institution researcher
        if "phd" in t or "ph.d" in t or "doctor" in t:
            return "InstitutionResearcher"
        # Otherwise could be industrial
        return "IndustrialResearcher"
    
    # 5. PhD Student
    phd_patterns = [
        "phd student", "ph.d student", "ph.d. student", 
        "doctoral student", "doctoral candidate", "phd candidate",
        "graduate student", "grad student",
    ]
    if any(p in t for p in phd_patterns):
        # Exclude if mentions master explicitly
        if not any(m in t for m in ["master", "msc", "m.s.", "m.sc."]):
            return "PhDStudent"
    
    # 6. Master Student (lowest priority)
    master_patterns = [
        "master student", "master's student", "msc student", "ms student",
        "m.s. student", "m.sc. student", "m.eng student",
    ]
    if any(p in t for p in master_patterns):
        return "MasterStudent"
    
    return "Unknown"


def classify_role_llm(role_text: str, api_key: str = None) -> dict:
    """LLM-based role classification
    
    Args:
        role_text: The role/position text to classify
        api_key: Optional API key for LLM calls
    
    Returns:
        dict with keys: "role_category", "rationale_short", "confidence"
    """
    if not role_text or not role_text.strip():
        return {"role_category": "Unknown", "rationale_short": "Empty input", "confidence": 1.0}
    
    try:
        from backend.llm import get_llm
        import json
        
        llm = get_llm("role_classifier", temperature=0.1, api_key=api_key)
        
        # Create comprehensive prompt with examples
        role_categories_str = ", ".join(config.ROLE_CATEGORIES.keys())
        
        prompt = f"""You are a strict talent classifier for recruitment purposes.

**Allowed categories ONLY**: {role_categories_str}, Unknown

**TASK**: Classify the *CURRENT* role in the given text. Return JSON only.

**CRITICAL RULES**:
1. IGNORE past degrees/positions (keywords: "received", "got my PhD/degree", "graduated", "former", "ex-", "previously", "was a")
2. ONLY use present-tense descriptions OR current titles WITHOUT temporal markers
3. If multiple current roles exist, pick highest-level (priority: Professor > Postdoc > IndustrialResearcher > InstitutionResearcher > PhDStudent > MasterStudent)
4. If nothing clear matches, output "Unknown"
5. "Research Scientist" at company/industry = IndustrialResearcher
6. "Research Scientist" at university/institute = InstitutionResearcher
7. Postdoc is separate from Professor (recent PhD graduate, temporary position)

**OUTPUT JSON FORMAT**:
{{
  "role_category": "<one of the allowed categories>",
  "rationale_short": "<max 15 words explaining decision>",
  "confidence": <0.0-1.0>
}}

**EXAMPLES**:

Input: "PhD student at MIT working on computer vision"
Output: {{"role_category": "PhDStudent", "rationale_short": "Currently PhD student", "confidence": 1.0}}

Input: "I received my Ph.D. degree from Stanford. Now Research Scientist at Google"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Current: Research Scientist at Google (company)", "confidence": 0.95}}

Input: "Master's student at CMU, interested in NLP"
Output: {{"role_category": "MasterStudent", "rationale_short": "Currently Master student", "confidence": 1.0}}

Input: "Assistant Professor of Computer Science at Berkeley"
Output: {{"role_category": "Professor", "rationale_short": "Assistant Professor position", "confidence": 1.0}}

Input: "Postdoctoral researcher at Harvard Medical School"
Output: {{"role_category": "Postdoc", "rationale_short": "Postdoctoral researcher", "confidence": 1.0}}

Input: "Research Scientist at Microsoft Research"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Industry researcher at Microsoft", "confidence": 0.9}}

Input: "Research Scientist, Institute for AI, ETH Zurich"
Output: {{"role_category": "InstitutionResearcher", "rationale_short": "Academic institution researcher", "confidence": 0.9}}

Input: "I got my PhD in 2020. Former postdoc. Currently software engineer at Apple."
Output: {{"role_category": "Unknown", "rationale_short": "Current role is software engineer, not researcher", "confidence": 0.8}}

Input: "PhD student and part-time Research Scientist at NVIDIA"
Output: {{"role_category": "IndustrialResearcher", "rationale_short": "Dual role, higher priority: IndustrialResearcher", "confidence": 0.85}}

**NOW CLASSIFY THIS**:
Role Text: "{role_text}"

Output JSON:"""

        response = llm.invoke(prompt)
        response_text = utils.strip_thinking(response.content if hasattr(response, 'content') else str(response))
        
        # Try to parse JSON
        # Remove markdown code blocks if present
        response_text = response_text.strip()
        if response_text.startswith("```"):
            # Extract content between ```json and ``` or ``` and ```
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1]) if len(lines) > 2 else response_text
        
        result = json.loads(response_text)
        
        # Validate result
        role_cat = result.get("role_category", "Unknown")
        if role_cat not in config.ROLE_CATEGORIES and role_cat != "Unknown":
            if config.VERBOSE:
                print(f"[classify_role_llm] Invalid category '{role_cat}', fallback to Unknown")
            role_cat = "Unknown"
        
        return {
            "role_category": role_cat,
            "rationale_short": result.get("rationale_short", "")[:100],
            "confidence": float(result.get("confidence", 0.5))
        }
        
    except Exception as e:
        if config.VERBOSE:
            print(f"[classify_role_llm] Error: {e}, falling back to rule-based")
        # Fallback to rule-based
        role_cat = classify_role_rule_based(role_text)
        return {
            "role_category": role_cat,
            "rationale_short": "LLM failed, rule-based classification",
            "confidence": 0.5 if role_cat != "Unknown" else 0.3
        }


def classify_role(role_text: str, api_key: str = None, use_llm: bool = None) -> str:
    """Main role classification function
    
    Args:
        role_text: The role/position text to classify
        api_key: Optional API key for LLM calls
        use_llm: Override config.ENABLE_LLM_DEGREE_MATCHING if specified
    
    Returns:
        One of the 6 role categories: MasterStudent, PhDStudent, Postdoc, 
        Professor, InstitutionResearcher, IndustrialResearcher, or "Unknown"
    """
    if use_llm is None:
        use_llm = config.ENABLE_LLM_DEGREE_MATCHING
    
    if use_llm:
        result = classify_role_llm(role_text, api_key)
        role_category = result["role_category"]
        
        if config.VERBOSE:
            print(f"[classify_role] Role: '{role_text[:80]}...'")
            print(f"[classify_role] Category: {role_category}")
            print(f"[classify_role] Rationale: {result['rationale_short']}")
            print(f"[classify_role] Confidence: {result['confidence']:.2f}")
        
        # If low confidence, also try rule-based and compare
        if result["confidence"] < 0.6:
            rule_result = classify_role_rule_based(role_text)
            if config.VERBOSE:
                print(f"[classify_role] Low confidence, rule-based suggests: {rule_result}")
            # If rule-based is not Unknown and different, consider using it
            if rule_result != "Unknown" and rule_result != role_category:
                if config.VERBOSE:
                    print(f"[classify_role] Using rule-based result due to low confidence")
                return rule_result
        
        return role_category
    else:
        return classify_role_rule_based(role_text)


def _role_matches_degree(role_text: str, degree_levels: List[str]) -> bool:
    """Rule-based degree matching function that checks current role vs degree requirements
    
    This function ensures proper matching:
    - If PhD is required, current role should be PhD student, not AP/Postdoc
    - If Master is required, current role should be Master student, not PhD student
    """
    t = (role_text or "").lower()
    if not degree_levels:
        return True
    degs = [d.lower() for d in degree_levels]
    
    # Define role patterns with their academic level
    role_patterns = {
        "phd_student": ["phd student", "doctoral student", "ph.d student", "phd candidate", "doctoral candidate"],
        "master_student": ["master student", "msc student", "ms student", "m.eng student", "m eng student"],
        "undergraduate_student": ["undergraduate student", "bachelor student", "bsc student", "bs student", "undergrad"],
        "graduate_student": ["graduate student", "grad student"],
        "assistant_professor": ["assistant professor", "ap", "assistant prof", "asst prof"],
        "associate_professor": ["associate professor", "assoc prof"],
        "professor": ["professor", "prof", "full professor"],
        "postdoc": ["postdoc", "post-doctoral", "post doctoral", "postdoctoral", "post-doc"],
        "researcher": ["researcher", "research scientist", "research fellow"],
    }
    
    # Check for overqualified positions first
    overqualified_patterns = ["assistant professor", "associate professor", "professor", "postdoc", "post-doctoral", "post doctoral", "postdoctoral"]
    
    # If any overqualified position is detected, check if it matches degree requirements
    for pattern in overqualified_patterns:
        if pattern in t:
            # If PhD is required and person is AP/Professor/Postdoc, they are overqualified
            if "phd" in degs and any(over in t for over in ["assistant professor", "associate professor", "professor", "postdoc", "post-doctoral"]):
                return False
            # If Master is required and person is PhD student or higher, they are overqualified
            if "master" in degs and any(over in t for over in ["phd student", "doctoral student", "assistant professor", "associate professor", "professor", "postdoc"]):
                return False
    
    # Check for appropriate matches
    for degree in degs:
        if degree == "phd":
            # PhD required - look for PhD student or equivalent
            if any(pattern in t for pattern in role_patterns["phd_student"] + role_patterns["graduate_student"]):
                return True
        elif degree in ["master", "msc", "ms"]:
            # Master required - look for Master student, not PhD student
            if any(pattern in t for pattern in role_patterns["master_student"] + role_patterns["graduate_student"]):
                # But exclude PhD students
                if not any(phd_pattern in t for phd_pattern in role_patterns["phd_student"]):
                    return True
        elif degree in ["bachelor", "undergraduate"]:
            # Bachelor required - look for undergraduate student
            if any(pattern in t for pattern in role_patterns["undergraduate_student"]):
                return True
    
    # If no specific match found, return False (strict matching)
    return False


def role_matches_degree(role_text: str, degree_levels: List[str], api_key: str = None) -> bool:
    """NEW: Main degree matching function using role classification system
    
    This is the new implementation that:
    1. First classifies the role into one of 6 categories
    2. Then checks if that category matches the degree requirements
    
    Args:
        role_text: The role/position text to analyze
        degree_levels: List of required degree levels (e.g., ['PhD', 'Master'])
        api_key: Optional API key for LLM calls
    
    Returns:
        bool: True if the role matches the degree requirements, False otherwise
    """
    # Empty degree requirements = accept all
    if not degree_levels:
        return True
    
    # Empty role text = reject
    if not role_text or not role_text.strip():
        return False
    
    # Step 1: Classify the role
    role_category = classify_role(role_text, api_key=api_key)
    
    if config.VERBOSE:
        print(f"[role_matches_degree] Role text: '{role_text[:80]}...'")
        print(f"[role_matches_degree] Classified as: {role_category}")
        print(f"[role_matches_degree] Required degrees: {degree_levels}")
    
    # Unknown role = reject (strict matching)
    if role_category == "Unknown":
        if config.VERBOSE:
            print(f"[role_matches_degree] Result: ❌ NO MATCH (Unknown category)")
        return False
    
    # Step 2: Check if role_category matches any of the degree requirements
    # Normalize degree levels to lowercase for comparison
    degree_levels_lower = [d.lower().strip() for d in degree_levels]
    
    # Check each degree requirement
    for degree in degree_levels_lower:
        # Get acceptable role categories for this degree
        acceptable_roles = config.DEGREE_TO_ROLE_MAPPING.get(degree, [])
        
        if role_category in acceptable_roles:
            if config.VERBOSE:
                print(f"[role_matches_degree] Result: ✅ MATCH ('{degree}' accepts '{role_category}')")
            return True
    
    # No match found
    if config.VERBOSE:
        print(f"[role_matches_degree] Result: ❌ NO MATCH")
    return False

def _overview_matches_spec(ov: CandidateOverview, spec: QuerySpec, api_key: str = None) -> bool:
    """Check CandidateOverview against student/degree requirements in QuerySpec.

    Uses both current_role_affiliation and current_status text for robust matching.
    
    Args:
        ov: Candidate overview to check
        spec: Query specification with requirements
        api_key: Optional API key for LLM calls
    """
    candidate_name = getattr(ov, "name", "Unknown")
    
    try:
        role_text = getattr(ov, "current_role_affiliation", "") or ""
        status_text = getattr(ov, "current_status", "") or ""

        # # Student requirement
        # if spec.must_be_current_student:
        #     if not utils.looks_like_student(role_text) and not utils.looks_like_student(
        #         status_text
        #     ):
        #         return False

        # Degree level requirement
        if spec.degree_levels:
            print(f"\n{'='*80}")
            print(f"[Degree Filter DEBUG] Checking: {candidate_name}")
            print(f"{'='*80}")
            print(f"Required degrees: {spec.degree_levels}")
            print(f"\n📋 Candidate info:")
            print(f"   Role: '{role_text}'")
            print(f"   Status: '{status_text}'")
            
            # Check role match
            role_match = role_matches_degree(role_text, spec.degree_levels, api_key)
            print(f"\n🔍 Role matching:")
            print(f"   Text: '{role_text}'")
            print(f"   Result: {'✅ MATCH' if role_match else '❌ NO MATCH'}")
            
            # Check status match
            status_match = role_matches_degree(status_text, spec.degree_levels, api_key)
            print(f"\n🔍 Status matching:")
            print(f"   Text: '{status_text}'")
            print(f"   Result: {'✅ MATCH' if status_match else '❌ NO MATCH'}")
            
            final_match = role_match or status_match
            
            if not final_match:
                print(f"\n❌ FILTERED: Neither role nor status matches required degrees")
                print(f"   Candidate: {candidate_name}")
                print(f"   Required: {spec.degree_levels}")
                print(f"   Role: {role_text[:100]}")
                print(f"   Status: {status_text[:100]}")
                print(f"{'='*80}\n")
                return False
            else:
                print(f"\n✅ PASSED: Degree requirement satisfied")
                print(f"   Candidate: {candidate_name}")
                print(f"   Matched via: {'role' if role_match else 'status'}")
                print(f"{'='*80}\n")

        return True
    except Exception as e:
        print(f"\n⚠️  EXCEPTION in _overview_matches_spec for {candidate_name}: {e}")
        # If anything goes wrong, be conservative and drop it when constraints exist
        if spec.must_be_current_student or spec.degree_levels:
            print(f"   → Filtering out due to exception with constraints")
            return False
        return True

def agent_execute_search(
    spec: QuerySpec, 
    api_key: str = None, 
    progress_callback=None,
    max_rounds_per_run: int = 2,
    resume_state: Optional[schemas.SearchTaskState] = None
) -> Union[schemas.SearchResults, schemas.PartialSearchResults]:
    """Run real pipeline: plan -> search -> select -> fetch -> extract -> filter -> score -> sort.
    
    Supports incremental search with user decision points every N rounds.
    
    Returns:
        - SearchResults: If search is complete (all candidates found or user chose to finish)
        - PartialSearchResults: If need user decision (after max_rounds_per_run)
    
    Args:
        spec: Query specification
        api_key: API key for LLM calls
        progress_callback: Optional callback function(event: str, progress: float) for progress updates
        max_rounds_per_run: Number of candidate pool processing rounds before pausing (default: 2)
        resume_state: Optional task state to resume from
    """
    from task_manager import create_task_state_from_spec, save_task_state
    
    def report_progress(event: str, pct: float, detail: Optional[schemas.ProgressDetail] = None):
        """Helper to safely report progress with optional detailed information"""
        if progress_callback:
            try:
                if detail:
                    # Send detailed progress information
                    progress_callback(event, pct, detail)
                else:
                    # Backward compatibility - just event and percentage
                    progress_callback(event, pct)
            except Exception:
                pass
    
    # Initialize or resume state
    if resume_state:
        task_id = resume_state.task_id
        terms = resume_state.terms
        pos = resume_state.pos
        rounds_completed = resume_state.rounds_completed
        candidates_accum = resume_state.candidates_accum
        all_serp = resume_state.all_serp
        sources = resume_state.sources
        all_scored_papers = resume_state.all_scored_papers
        search_candidate_set = set(resume_state.search_candidate_set)
        selected_urls_set = resume_state.selected_urls_set
        selected_serp_url_set = resume_state.selected_serp_url_set
    else:
        # Start new search
        detail = schemas.ProgressDetail(
            event="parsing",
            progress=0.05,
            current_action="Planning search strategy and keywords",
            target_candidates=spec.top_n
        )
        report_progress("parsing", 0.05, detail)
        terms = _plan_terms(spec)
        # Create new task state
        state = create_task_state_from_spec(spec, terms)
        task_id = state.task_id
        pos = 0
        rounds_completed = 0
        candidates_accum = {}
        all_serp = []
        sources = {}
        all_scored_papers = {}
        search_candidate_set = set()
        selected_urls_set = set()
        selected_serp_url_set = set()
    chunk = config.SEARCH_BATCH_CHUNK
    rounds_this_run = 0  # Track rounds in current run
    
    # Main search loop - continue until run out of terms (no early stopping based on candidate count)
    while pos < len(terms):
        # Increment round counters at the START of each round
        rounds_completed += 1
        rounds_this_run += 1
        print(f"[Round {rounds_completed}] Starting round {rounds_completed} (run: {rounds_this_run}/{max_rounds_per_run})")
        print(f"[Round {rounds_completed}] Current candidates: {len(candidates_accum)}, Target: {spec.top_n}")
        
        batch_terms = terms[pos : pos + chunk]
        pos += chunk
        
        # Report search progress (10% - 30%)
        search_progress = 0.10 + (pos / len(terms)) * 0.20
        # Calculate actual search terms for this batch
        current_terms_sample = batch_terms[:3] if len(batch_terms) > 3 else batch_terms
        terms_preview = " | ".join([f'"{t}"' for t in current_terms_sample])
        if len(batch_terms) > 3:
            terms_preview += f" ... (+{len(batch_terms)-3} more)"
        
        detail = schemas.ProgressDetail(
            event="searching",
            progress=search_progress,
            current_action="Searching academic papers",
            search_terms_batch=rounds_completed,
            search_terms_total=len(terms) // chunk + (1 if len(terms) % chunk else 0),
            found_candidates=len(candidates_accum),
            target_candidates=spec.top_n,
            extra_info={
                "search_terms": terms_preview,
                "batch_size": len(batch_terms),
                "total_terms": len(terms),
                "venues": ", ".join(spec.venues[:3]) if spec.venues else "All venues",
                "years": f"{min(spec.years)}-{max(spec.years)}" if spec.years else "All years"
            }
        )
        report_progress("searching", search_progress, detail)
        
        # Use function defaults: pages=1, k_per_query=6 (more conservative to avoid rate limiting)
        serp = _run_search_terms(batch_terms)
        all_serp.extend(serp)
        
        # ========== 【新增】论文打分和分档 ==========
        if config.USE_LLM_PAPER_SCORING and serp:
            print(f"\n[Round {rounds_completed}] 📊 Starting paper scoring for {len(serp)} papers...")
            
            # Get LLM instance for scoring
            llm_instance = llm.get_llm("select", temperature=0.3, api_key=api_key)
            
            # Build query string from spec
            query_parts = []
            if spec.keywords:
                query_parts.extend(spec.keywords)
            if spec.research_field:
                query_parts.append(spec.research_field)
            user_query = " ".join(query_parts) or "research papers"
            
            # Parallel scoring with two-tier classification
            ranked_papers = score_and_rank_papers_parallel(
                serp=serp,
                user_query=user_query,
                llm=llm_instance,
                min_score=5  # Only keep papers with score >= 5
            )
            
            print(f"[Round {rounds_completed}] ✅ Paper scoring complete: {len(ranked_papers)}/{len(serp)} papers passed filter\n")
            
            # Use ranked papers instead of original serp
            serp_to_process = ranked_papers
        else:
            # If LLM scoring disabled, use all papers
            print(f"[Round {rounds_completed}] ⚠️ LLM paper scoring disabled, using all {len(serp)} papers")
            serp_to_process = serp
        
        # Extract first authors from scored/filtered papers
        new_candidates_count = 0
        tier1_candidates = 0
        tier0_candidates = 0
        filter_first_author_name_set = set()
        if search_candidate_set:
            filter_first_author_name_set = set(first_name for first_name, _, _, _ in search_candidate_set)
        
        print(f"\n[Round {rounds_completed}] 👥 Extracting first authors from ranked papers...")
        
        for item in serp_to_process:
            authors = item.get("authors", [])
            if authors:
                first_author = authors[0] if isinstance(authors[0], dict) else {"name": str(authors[0])}
                author_name = first_author.get("name", "").strip()
                author_id = first_author.get("id", None)  # 提取 Semantic Scholar ID
                paper_title = item.get("title", "").strip()
                paper_url = item.get("url", "").strip()
                paper_score = item.get("score", 0)  # Get LLM score
                paper_tier = item.get("relevant_tier", 0)  # Get tier
                
                if author_name and paper_title and author_name not in filter_first_author_name_set:
                    filter_first_author_name_set.add(author_name)
                    search_candidate_set.add((author_name, author_id, paper_title, paper_url))  # 4元组
                    new_candidates_count += 1
                    
                    # Count by tier
                    if paper_tier == 1:
                        tier1_candidates += 1
                    else:
                        tier0_candidates += 1
                    
                    # Record paper score to all_scored_papers
                    if paper_url and paper_url not in all_scored_papers:
                        all_scored_papers[paper_url] = schemas.PaperWithScore(
                            url=paper_url,
                            title=paper_title,
                            abstract=item.get("abstract", "") or item.get("snippet", ""),
                            score=paper_score,
                            relevant_tier=paper_tier,
                            completeness_score=0.0,  # Not used in new scoring
                            associated_candidates=[]
                        )
        
        # Print candidate extraction statistics
        print(f"[Round {rounds_completed}] ✅ Candidate extraction complete:")
        print(f"  New candidates: {new_candidates_count}")
        print(f"  └─ From Tier 1 papers (7-8分): {tier1_candidates} candidates")
        print(f"  └─ From Tier 0 papers (1-6分): {tier0_candidates} candidates")
        print(f"  Total in pool: {len(search_candidate_set)}\n")
        # Report fetching progress (30% - 40%)
        detail = schemas.ProgressDetail(
            event="analyzing",
            progress=0.49,
            current_action="Processing candidate information",
            items_processed=len(selected_urls_set),
            found_candidates=len(candidates_accum),
            target_candidates=spec.top_n,
            extra_info={
                "candidates_in_pool": len(search_candidate_set),
                "papers_with_abstracts": len([item for item in serp if item.get("abstract")]),
            }
        )
        report_progress("searching", 0.49, detail)
        if len(search_candidate_set) == 0:
            print(f"[agent.execute_search] New candidates added to search pool: {len(filter_first_author_name_set)}")
        else:
            items = list(search_candidate_set)
            max_workers = min(len(items), 30)
            def _submit_one(ex, first_name, first_id, paper_title, paper_url):
                return ex.submit(
                    orchestrate_candidate_report,
                    first_author=first_name,
                    paper_title=paper_title,
                    paper_url=paper_url,
                    aliases=[first_name],
                    author_id=first_id,  # 传递 Semantic Scholar ID
                    api_key=api_key,
                )
                    
            # Report candidate analysis start (50% - 80% will be dynamic)
            detail = schemas.ProgressDetail(
                event="analyzing",
                progress=0.50,
                current_action="Starting candidate evaluation",
                items_total=len(items),
                found_candidates=len(candidates_accum),
                target_candidates=spec.top_n,
                extra_info={
                    "candidates_to_analyze": len(items),
                    "matches_so_far": len(candidates_accum),
                    "round": rounds_completed,
                    "parallel_workers": max_workers
                }
            )
            report_progress("analyzing", 0.50, detail)
                    
            print("="*50)
            print(f"[agent.execute_search] start submit search candidate task with: {len(items)} candidates")
            print(f"[agent.execute_search] start submit tasks with max_workers: {max_workers}")
            print(f'API key: {api_key}')
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                # Submit initial window up to max_workers
                idx = 0
                futures = {}
                while idx < len(items) and len(futures) < max_workers:
                    first_name, first_id, paper_title, paper_url = items[idx]
                    fut = _submit_one(ex, first_name, first_id, paper_title, paper_url)
                    futures[fut] = (first_name, first_id, paper_title, paper_url)
                    idx += 1

                # Process as they complete; process all candidates in this round (no early stopping)
                while futures:
                    for fut in as_completed(list(futures.keys()), timeout=None):
                        first_name, first_id, paper_title, paper_url = futures.pop(fut)
                                
                        # remove this candidate from search_candidate_set
                        search_candidate_set.remove((first_name, first_id, paper_title, paper_url))
                        try:
                            profile, overview, eval_res = fut.result()
                        except Exception as e:
                            print(f"[orchestrate] {first_name} error: {e}")
                            profile, overview = None, None

                        if overview:
                            if _overview_matches_spec(overview, spec, api_key):
                                print(f"[agent.execute_search] add candidate to candidates_accum: {first_name}")
                                candidates_accum[first_name] = overview
                                # Record paper-to-candidate mapping
                                if paper_url and paper_url in all_scored_papers:
                                    if first_name not in all_scored_papers[paper_url].associated_candidates:
                                        all_scored_papers[paper_url].associated_candidates.append(first_name)
                            else:
                                print(f"[agent.execute_search] {first_name} -> overview not matches spec filtered")
                            
                            # Report dynamic analyzing progress (50% - 75%)
                            # Use max of spec.top_n and current count to avoid division by zero
                            target_for_progress = max(spec.top_n, len(candidates_accum) + 1)
                            analyzing_progress = 0.50 + min(len(candidates_accum) / target_for_progress, 1.0) * 0.25
                                    
                            # Count processed and remaining
                            processed_count = len(items) - len(search_candidate_set)
                            detail = schemas.ProgressDetail(
                                        event="analyzing",
                                        progress=min(analyzing_progress, 0.75),
                                        current_action=f"Analyzing candidate: {first_name}",
                                        items_processed=processed_count,
                                        items_total=len(items),
                                        found_candidates=len(candidates_accum),
                                        target_candidates=spec.top_n,
                                        current_candidate=first_name,
                                        extra_info={
                                            "active_workers": len(futures),
                                            "matches_found": len(candidates_accum)
                                        }
                            )
                            report_progress("analyzing", min(analyzing_progress, 0.75), detail)
                                    
                            print(f"[agent.execute_search] current found candidates: {len(candidates_accum)}")
                            print(f"[agent.execute_search] target: {spec.top_n}")
                        else:
                            print(f"[orchestrate] {first_name} -> overview is None")

                        # Rolling window: submit next task to keep max_workers saturated
                        if idx < len(items):
                            next_first_name, next_first_id, next_paper_title, next_paper_url = items[idx]
                            print(f"[Rolling Window] Submitting next candidate: {next_first_name} ({idx+1}/{len(items)})")
                            nfut = _submit_one(ex, next_first_name, next_first_id, next_paper_title, next_paper_url)
                            futures[nfut] = (next_first_name, next_first_id, next_paper_title, next_paper_url)
                            idx += 1
                            print(f"[Rolling Window] Active workers: {len(futures)}, Processed: {idx}/{len(items)})")

                        # Report progress every few candidates
                        if idx % 3 == 0 or idx == len(items):  # Update every 3 candidates or at the end
                                    progress_pct = 0.50 + (idx / len(items)) * 0.25
                                    # Use first_name as current candidate (the one just processed)
                                    detail = schemas.ProgressDetail(
                                        event="analyzing",
                                        progress=min(progress_pct, 0.75),
                                        current_action="Evaluating candidates",
                                        items_processed=idx - len(futures),  # Completed count
                                        items_total=len(items),
                                        found_candidates=len(candidates_accum),
                                        target_candidates=spec.top_n,
                                        current_candidate=first_name,
                                        extra_info={
                                            "active_workers": len(futures),
                                            "matches_found": len(candidates_accum),
                                            "queue_remaining": len(items) - idx
                                        }
                                    )
                                    report_progress("analyzing", min(progress_pct, 0.75), detail)
        
        # ========== End of round - check if we need to pause ==========
        print(f"\n[Round {rounds_completed}] ✅ This round of processing is complete")
        print(f"  - Current candidate number: {len(candidates_accum)}/{spec.top_n}")
        print(f"  - This run completed rounds: {rounds_this_run}/{max_rounds_per_run}")
        
        # Check if we need to pause and ask user for decision
        if rounds_this_run >= max_rounds_per_run:
            current_cycle = rounds_completed // 2
            print(f"[Pause] Cycle information:")
            print(f"  - Completed cycle number: {current_cycle}")
            print(f"  - Completed rounds: {rounds_completed}")
            print(f"  - Accumulated candidates: {len(candidates_accum)}")
            if candidates_accum:
                print(f"  - Candidate list: {list(candidates_accum.keys())[:5]}...")
            print(f"  - Search progress: {pos}/{len(terms)} search terms")
            
            # Save task state
            task_state = schemas.SearchTaskState(
                task_id=task_id,
                spec=spec,
                pos=pos,
                terms=terms,
                rounds_completed=rounds_completed,
                candidates_accum=candidates_accum,
                all_serp=all_serp,
                sources=sources,
                all_scored_papers=all_scored_papers,
                search_candidate_set=list(search_candidate_set),
                selected_urls_set=selected_urls_set,
                selected_serp_url_set=selected_serp_url_set,
            )
            save_task_state(task_state)
            
            # Return partial results and ask user
            # Calculate current cycle (2 rounds = 1 cycle)
            current_cycle = rounds_completed // 2
            
            print(f"[Pause] Prepare to return PartialSearchResults:")
            print(f"  - task_id: {task_id}")
            print(f"  - rounds_completed: {rounds_completed}")
            print(f"  - total_candidates_found: {len(candidates_accum)}")
            print(f"  - current_candidates number: {len(candidates_accum)}")
            print(f"  ⚠️ Attention: candidates are not sorted (sorting will be done when user chooses 'finish')")
            
            # Use model_construct to avoid re-validation of already validated Pydantic objects
            partial_result = schemas.PartialSearchResults.model_construct(
                task_id=task_id,
                need_user_decision=True,
                rounds_completed=rounds_completed,
                total_candidates_found=len(candidates_accum),
                current_candidates=list(candidates_accum.values()),  # Return raw list without sorting
                message=f"Completed the {current_cycle} search cycle ({rounds_completed} rounds), found {len(candidates_accum)} candidates."
            )
            return partial_result
    # ========== RANKING & SCORING (Step 3) - Outside search loop ==========
    # Report ranking progress (75% - 85%)
    detail = schemas.ProgressDetail(
        event="ranking",
        progress=0.78,
        current_action="Ranking and scoring candidates",
        found_candidates=len(candidates_accum),
        target_candidates=spec.top_n,
        extra_info={
            "total_candidates": len(candidates_accum),
            "papers_evaluated": len(all_scored_papers),
            "search_rounds": rounds_completed
        }
    )
    report_progress("ranking", 0.78, detail)
    
    # Create task state for final processing
    final_task_state = schemas.SearchTaskState(
        task_id=task_id,
        spec=spec,
        pos=pos,
        terms=terms,
        rounds_completed=rounds_completed,
        candidates_accum=candidates_accum,
        all_serp=all_serp,
        sources=sources,
        all_scored_papers=all_scored_papers,
        search_candidate_set=list(search_candidate_set),
        selected_urls_set=selected_urls_set,
        selected_serp_url_set=selected_serp_url_set,
    )
    
    # Report ranking progress (85% - 90%)
    detail = schemas.ProgressDetail(
        event="ranking",
        progress=0.88,
        current_action="Applying filters and sorting",
        found_candidates=len(candidates_accum),
        target_candidates=spec.top_n
    )
    report_progress("ranking", 0.88, detail)
    
    # Report finalizing progress (90% - 95%)
    detail = schemas.ProgressDetail(
        event="finalizing",
        progress=0.92,
        current_action="Preparing final results",
        found_candidates=len(candidates_accum),
        target_candidates=spec.top_n
    )
    report_progress("finalizing", 0.92, detail)
    
    # Use unified finish function to rank and prepare results
    results = agent_finish_search(final_task_state, api_key)
    
    # Report completion (100%)
    detail = schemas.ProgressDetail(
        event="done",
        progress=1.0,
        current_action="Search completed",
        found_candidates=len(candidates_accum),
        target_candidates=spec.top_n
    )
    report_progress("done", 1.0, detail)
    
    return results

def agent_finish_search(task_state: schemas.SearchTaskState, api_key: str = None) -> schemas.SearchResults:
    """Finish a paused search task by ranking and returning current candidates.
    
    This is called when the user chooses to stop searching and view current results.
    
    Args:
        task_state: SearchTaskState containing accumulated candidates and papers
        api_key: API key for LLM calls (if needed)
        
    Returns:
        SearchResults with final ranked candidates
    """
    print(f"[agent.finish_search] Input data:")
    print(f"  - Task ID: {task_state.task_id}")
    print(f"  - Total candidate number: {len(task_state.candidates_accum)}")
    if task_state.candidates_accum:
        print(f"  - Candidate list: {list(task_state.candidates_accum.keys())[:10]}...")
    print(f"  - Total paper number: {len(task_state.all_scored_papers)}")
    print(f"  - Target Top N: {task_state.spec.top_n}")    
    # Get spec from task state
    spec = task_state.spec
    candidates_accum = task_state.candidates_accum
    all_scored_papers = task_state.all_scored_papers
    
    # Sort candidates by total_score
    ranked = sorted(
        candidates_accum.values(),
        key=lambda x: getattr(x, "total_score", 0),
        reverse=True,
    )
    
    # Split into recommended and additional
    recommended = ranked[: spec.top_n]
    additional = ranked[spec.top_n:]
    
    # Sort reference papers by score (descending)
    reference_papers = sorted(
        all_scored_papers.values(),
        key=lambda x: (x.relevant_tier, x.completeness_score, x.score),
        reverse=True
    )
    
    # Build user query for metadata
    query_parts = []
    if spec.keywords:
        query_parts.append(" ".join(spec.keywords))
    if spec.venues:
        query_parts.append(f"conferences: {', '.join(spec.venues)}")
    user_query = " ".join(query_parts) or "research papers"
    
    # Create and return SearchResults
    # Use model_construct to avoid re-validation of already validated Pydantic objects
    results = schemas.SearchResults.model_construct(
        recommended_candidates=recommended,
        additional_candidates=additional,
        reference_papers=reference_papers,
        total_candidates_found=len(ranked),
        search_query=user_query
    )
    
    print(f"\n[agent.finish_search] ✅ Sorting completed, returning results:")
    print(f"  - Recommended candidates: {len(recommended)}")
    if recommended:
        print(f"    → {[c.name for c in recommended[:5]]}")
    print(f"  - Additional candidates: {len(additional)}")
    if additional:
        print(f"    → {[c.name for c in additional[:3]]}")
    print(f"  - Reference papers: {len(reference_papers)}")
    print(f"  - Total candidates: {len(ranked)}")
    print("🏁"*50 + "\n")
    
    return results

def agent_adjust_search_parameters(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] = None,
) -> QuerySpec | None:
    """
    Use LLM to adjust search parameters based on a new user instruction and recent chat history.

    Args:
        current_spec: Existing query spec as dict
        user_input: New user adjustment instruction
        chat_history: Optional recent chat messages as a list of {"role": "user"|"assistant", "content": str}

    Returns:
        QuerySpec: Updated query spec
    """
    try:
        llm_instance = llm.get_llm("adjust", temperature=0.2)

        # Clamp history to last 10 messages
        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        # Prepare a compact history string
        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        prompt = (
            "SYSTEM ROLE: You update a structured search spec for a recruitment/talent search engine.\n"
            "You MUST output STRICT JSON matching the QuerySpec schema (no extra keys, no comments, no prose).\n"
            "\n"
            "OBJECTIVE\n"
            "Given (1) the current JSON spec, (2) a new user instruction, and (3) recent conversation snippets,\n"
            "produce an UPDATED QuerySpec where ONLY the fields explicitly changed by the new instruction are modified.\n"
            "All other fields must remain identical to the current spec.\n"
            "\n"
            "SCHEMA (QuerySpec):\n"
            "{\n"
            '  "top_n": int,\n'
            '  "years": int[],\n'
            '  "venues": string[],\n'
            '  "keywords": string[],\n'
            '  "must_be_current_student": bool,\n'
            '  "degree_levels": string[],\n'
            '  "author_priority": string[],\n'
            '  "extra_constraints": string[]\n'
            "}\n"
            "\n"
            "PRECEDENCE & EDIT RULES (VERY IMPORTANT)\n"
            "1) New User Instruction > recent conversation context > Current Spec.\n"
            '2) If the instruction includes ADDITIVE language (e.g., "also include X", "add Y"), then UNION with the existing list.\n'
            '3) If it includes EXCLUSIVE language (e.g., "only X", "strictly X", "limit to X"), then REPLACE the list with exactly those items.\n'
            '4) If it includes NEGATION (e.g., "exclude X", "not X", "no X"), REMOVE those items from the list if present.\n'
            "5) If a field is NOT mentioned, DO NOT change it.\n"
            '6) For numbers in "top_n", parse the most salient integer in the instruction ("~", "around", "at least" → just use the integer).\n'
            '7) Years: extract explicit 4-digit years if present; if phrases like "last 2 years" appear, map to [CURRENT_YEAR, CURRENT_YEAR-1].\n'
            "   If years are not mentioned, DO NOT change them.\n"
            '8) must_be_current_student: set True if the instruction says "current/enrolled/active students only"; set False if it says\n'
            '   "alumni allowed", "graduates ok", "postdocs ok", or similar. If not mentioned, DO NOT change it.\n'
            "\n"
            "NORMALIZATION RULES\n"
            "- Venues canonicalization (case-insensitive → canonical UPPER names). Known venues include: {conf_list}.\n"
            '  Synonyms map to canonical: {"NIPS":"NeurIPS", "The Web Conference":"WWW", "WWW":"WWW"}.\n'
            "  Deduplicate while preserving the user-specified order.\n"
            '- Degree levels canonical set: ["PhD", "MSc", "Master", "Graduate", "Undergraduate", "Bachelor", "Postdoc"].\n'
            '  Map synonyms: {"MS":"MSc", "M.S.":"MSc", "MEng":"Master", "BSc":"Bachelor", "BS":"Bachelor"}.\n'
            '- Author priority canonical set: ["first", "last", "corresponding"]. Map synonyms: {"lead":"first", "senior":"last"}.\n'
            "- Keywords: trim whitespace, lower-case, deduplicate.\n"
            "\n"
            "CONSTRAINTS\n"
            "- ABSOLUTELY DO NOT invent defaults or remove existing values unless the instruction explicitly requests it or implies it\n"
            "  via exclusive/negation phrasing. If ambiguous, prefer ADD (union) rather than replace.\n"
            "- Output MUST be valid JSON for QuerySpec, including ALL fields. No nulls. No extra commentary.\n"
            "\n"
            "INPUTS\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n"
            "\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n"
            "\n"
            "=== New User Instruction ===\n"
            f"{user_input}\n"
            "\n"
            "OUTPUT FORMAT\n"
            "Return ONLY the final JSON for QuerySpec. No markdown, no code fences, no explanations.\n"
        )

        # Use schemas.QuerySpec for structured parsing
        adjusted = llm.safe_structured(llm_instance, prompt, schemas.QuerySpec)

        # If venues empty, apply sensible default: 3个核心会议 + 随机2个顶会
        if adjusted.venues == []:
            import random
            core_venues = config.CORE_CONFERENCES.copy()
            random_venues = random.sample(config.TOP_TIER_CONFERENCES, min(2, len(config.TOP_TIER_CONFERENCES)))
            adjusted.venues = core_venues + random_venues
            print(f"[Adjust Params] No venues after adjustment, using default:")
            print(f"  Core: {core_venues}")
            print(f"  Random: {random_venues}")
            print(f"  Final: {adjusted.venues}")

        return adjusted
    except Exception as e:
        return None

def agent_classify_user_adjustment(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] | None = None,
) -> Dict[str, Any]:
    """
    Classify whether the user input is requesting a change to search parameters.

    Returns a dict: {"is_adjustment": bool, "help_instruction": str}
    If is_adjustment is False, help_instruction contains a concise instruction for the user.
    """
    try:
        llm_instance = llm.get_llm("classify", temperature=0.0)

        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        prompt = (
            "SYSTEM: You classify if the user's new message is asking to ADJUST the search parameters (like top_n, years, venues, keywords, must_be_current_student, degree_levels, author_priority, extra_constraints) or not.\n"
            'Return STRICT JSON with keys: {"is_adjustment": bool, "help_instruction": string}.\n'
            "If the message is NOT an adjustment (e.g., greeting, question, generic feedback without parameters), set is_adjustment=false and provide a short, concrete help_instruction that tells the user exactly how to specify changes (one sentence).\n"
            "If it IS an adjustment, set is_adjustment=true and help_instruction=''.\n\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n\n"
            "=== New User Message ===\n"
            f"{user_input}\n\n"
            "OUTPUT: JSON only."
        )

        result = llm.safe_structured(
            llm_instance, prompt, schemas.UserAdjustmentClassification
        )
        # Expecting UserAdjustmentClassification object
        if isinstance(result, schemas.UserAdjustmentClassification):
            is_adjustment = result.is_adjustment
            help_instruction = result.help_instruction if not is_adjustment else ""
            return {
                "is_adjustment": is_adjustment,
                "help_instruction": help_instruction,
            }
        # Fallback
        is_adjustment = any(
            k in user_input.lower()
            for k in [
                "add",
                "remove",
                "only",
                "exclude",
                "top",
                "year",
                "venue",
                "keyword",
                "student",
                "degree",
                "author",
            ]
        )
        return {
            "is_adjustment": is_adjustment,
            "help_instruction": (
                "Please specify what to change, e.g., 'top_n 15' or 'add keywords: computer vision'."
                if not is_adjustment
                else ""
            ),
        }
    except Exception as e:
        print(f"LLM分类失败, 返回原始参数: {e.message}")
        return {
            "is_adjustment": False,
            "help_instruction": "Tell me what to change, e.g., 'set top_n to 15' or 'add venues: ACL, EMNLP'.",
        }


def agent_validate_search_request(
    user_input: str, chat_history: List[Dict[str, str]] | None = None
) -> Dict[str, Any]:
    """
    Validate whether the user input contains sufficient information for a meaningful search.

    Returns a dict: {"is_valid_search": bool, "search_terms_found": List[str],
                     "missing_elements": List[str], "suggestion": str}
    """
    try:
        llm_instance = llm.get_llm("validate", temperature=0.0)

        chat_history = chat_history or []
        recent_msgs = chat_history[-5:]  # Only look at recent context

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        prompt = (
            "SYSTEM: You validate if the user's message contains enough information for a meaningful talent search.\n"
            "IMPORTANT: Respond ONLY in English. All output must be in English.\n\n"
            "A valid search should contain at least one of:\n"
            "- Research areas/topics (e.g., 'machine learning', 'computer vision', 'NLP')\n"
            "- Academic terms (e.g., 'PhD students', 'researchers', 'graduate students')\n"
            "- Specific skills or expertise\n"
            "- Academic venues or conferences\n"
            "- Career stage or degree level\n\n"
            'Return STRICT JSON with keys: {"is_valid_search": bool, "search_terms_found": [str], "missing_elements": [str], "suggestion": str}.\n'
            "If valid, set is_valid_search=true and list the search terms found.\n"
            "If invalid, set is_valid_search=false, list what's missing, and provide a helpful suggestion.\n\n"
            "=== Recent Conversation ===\n"
            f"{history_text}\n\n"
            "=== User Message to Validate ===\n"
            f"{user_input}\n\n"
            "OUTPUT: JSON only."
        )

        result = llm.safe_structured(
            llm_instance, prompt, schemas.SearchValidationResult
        )

        if isinstance(result, schemas.SearchValidationResult):
            return {
                "is_valid_search": result.is_valid_search,
                "search_terms_found": result.search_terms_found,
                "missing_elements": result.missing_elements,
                "suggestion": result.suggestion,
            }

        # Fallback
        has_research_terms = any(
            term in user_input.lower()
            for term in [
                "machine learning",
                "ai",
                "artificial intelligence",
                "computer vision",
                "nlp",
                "natural language",
                "deep learning",
                "neural",
                "research",
                "phd",
                "student",
                "graduate",
                "academic",
                "paper",
                "publication",
                "conference",
                "journal",
            ]
        )

        return {
            "is_valid_search": has_research_terms,
            "search_terms_found": (
                [] if not has_research_terms else ["research terms detected"]
            ),
            "missing_elements": (
                [] if has_research_terms else ["research areas", "academic context"]
            ),
            "suggestion": (
                "Please specify what type of talent you're looking for, including research areas or academic background."
                if not has_research_terms
                else ""
            ),
        }

    except Exception as e:
        print(f"Search validation failed: {e}")
        return {
            "is_valid_search": False,
            "search_terms_found": [],
            "missing_elements": ["clear search criteria"],
            "suggestion": "Please describe what type of talent you're looking for, including research areas or academic background.",
        }


def agent_diff_search_parameters(
    current_spec: Dict[str, Any],
    user_input: str,
    chat_history: List[Dict[str, str]] | None = None,
) -> QuerySpecDiff | None:
    """
    Use LLM to produce a PARTIAL update (diff) for QuerySpec. Only include fields that change.
    """
    try:
        llm_instance = llm.get_llm("adjust_diff", temperature=0.2)

        chat_history = chat_history or []
        recent_msgs = chat_history[-10:]

        def fmt(m):
            role = m.get("role", "user")
            content = m.get("content", "").strip()
            return f"{role.upper()}: {content}"

        history_text = "\n".join(fmt(m) for m in recent_msgs)

        conf_list = ", ".join(config.DEFAULT_CONFERENCES.keys())
        prompt = (
            "SYSTEM ROLE: You update a structured search spec for a recruitment/talent search engine.\n"
            "You MUST output STRICT JSON matching the QuerySpecDiff schema (omit fields that do not change).\n\n"
            "OBJECTIVE\n"
            "Given (1) the current JSON spec, (2) a new user instruction, and (3) recent conversation snippets,\n"
            "produce a PARTIAL QuerySpecDiff with ONLY the fields changed by the new instruction.\n\n"
            "SCHEMA (QuerySpecDiff): {"
            " 'top_n': int?, 'years': int[]?, 'venues': string[]?, 'keywords': string[]?, 'must_be_current_student': bool?, 'degree_levels': string[]?, 'author_priority': string[]?, 'extra_constraints': string[]? }\n\n"
            "EDIT RULES\n"
            "- ADDITIVE language (e.g., 'also include X', 'add Y'): union with existing list and return the NEW list for that field.\n"
            "- EXCLUSIVE language (e.g., 'only X', 'strictly X', 'limit to X'): replace the list with exactly those items.\n"
            "- NEGATION (e.g., 'exclude X', 'no X'): remove those items if present and return the NEW list.\n"
            "- If a field is NOT mentioned, DO NOT include it in the output.\n"
            "- Numbers: set 'top_n' to the salient integer.\n"
            "- Years: handle explicit years or phrases like 'last 2 years' to [CURRENT_YEAR, CURRENT_YEAR-1]. If not mentioned, omit.\n\n"
            "NORMALIZATION\n"
            f"- Venues canonicalization. Known venues include: {conf_list}. Map 'NIPS'->'NeurIPS', 'The Web Conference'->'WWW'. Deduplicate, preserve user order.\n"
            "- Degree levels canonical set: ['PhD','MSc','Master','Graduate','Undergraduate','Bachelor','Postdoc'] with common synonyms.\n"
            "- Author priority canonical set: ['first','last','corresponding'] (lead->first, senior->last).\n"
            "- Keywords: lower-case, trim, deduplicate.\n\n"
            "CONSTRAINTS\n"
            "- Output MUST be valid JSON for QuerySpecDiff. No markdown, no prose.\n\n"
            "INPUTS\n"
            "=== Conversation (most recent last) ===\n"
            f"{history_text}\n\n"
            "=== Current Spec (JSON) ===\n"
            f"{json.dumps(current_spec, ensure_ascii=False)}\n\n"
            "=== New User Instruction ===\n"
            f"{user_input}\n\n"
            "OUTPUT FORMAT\n"
            "Return ONLY the final JSON for QuerySpecDiff."
        )

        diff = llm.safe_structured(llm_instance, prompt, QuerySpecDiff)
        return diff
    except Exception:
        return None


def merge_query_spec_with_diff(
    base_spec: Dict[str, Any], diff: QuerySpecDiff
) -> Dict[str, Any]:
    """Apply QuerySpecDiff fields onto base_spec and return a new dict."""
    try:
        updated = dict(base_spec)
        data = diff.dict(exclude_none=True)
        for k, v in data.items():
            updated[k] = v
        return updated
    except Exception:
        # Safe fallback: return original
        return base_spec


def node_parse_query(state: ResearchState) -> Dict[str, Any]:
    """
    Node function for parsing queries in the research workflow

    Args:
        state: Current research state

    Returns:
        Updated state with parsed query
    """
    # 这个函数用于工作流系统
    # 暂时直接返回状态
    return state


if __name__ == "__main__":
    agent_search_input = QuerySpec(
        top_n=3,
        years=[2025, 2024],
        venues=[
            "ICLR",
            "ICML",
            "NeurIPS",
            "ACL",
            "EMNLP",
            "NAACL",
            "KDD",
            "WWW",
            "AAAI",
            "IJCAI",
            "CVPR",
            "ECCV",
            "ICCV",
            "SIGIR",
        ],
        keywords=["LLM", "Large Language Model", "graph neural network"],
        must_be_current_student=True,
        degree_levels=["PhD", "MSc"],
        author_priority=["first", "last"],
        extra_constraints=[],
    )

    # For testing, you may need to provide an API key
    # agent_execute_search(agent_search_input, api_key="your_api_key_here")
    print("Test code disabled - requires API key")
def agent_generate_search_summary(results, query_spec):
    total = len(results.recommended_candidates) + len(results.additional_candidates)
    areas = []
    for c in results.recommended_candidates[:3]:
        if hasattr(c, 'research_focus'):
            areas.extend(c.research_focus[:2])
    
    areas_text = ", ".join(list(set(areas))[:5]) if areas else "relevant research areas"
    return f"Found {total} candidates specializing in {areas_text}."