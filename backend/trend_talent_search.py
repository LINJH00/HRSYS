
"""
Trend Radar talent search integration module
Integrate Targeted Search SearXNG functionality into Trend Radar
"""

import sys
import os
import re
import json
import time
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import asdict

# Add trend_radar_search to path
current_dir = os.path.dirname(__file__)
trend_radar_search = os.path.join(current_dir, 'trend_radar_search')
if trend_radar_search not in sys.path:
    sys.path.append(trend_radar_search)

# Step-by-step import for better error messages
missing_deps = []
TALENT_SEARCH_AVAILABLE = False

try:
    # 检查核心依赖
    try:
        import requests
    except ImportError:
        missing_deps.append("requests")
    
    try:
        import bs4
    except ImportError:
        missing_deps.append("beautifulsoup4")
    
    try:
        import trafilatura
    except ImportError:
        missing_deps.append("trafilatura")
    
    if missing_deps:
        print(f"[WARNING] Missing dependencies: {', '.join(missing_deps)}")
        print(f"[INFO] Please run: pip install {' '.join(missing_deps)}")
        raise ImportError(f"Missing dependencies: {missing_deps}")
    
    # Import targeted search core functionality
    from trend_radar_search.search import searxng_search
    from trend_radar_search.agents import agent_execute_search, _run_search_terms
    from trend_radar_search.author_discovery import discover_author_profile
    from trend_radar_search.extraction import synthesize_candidates
    from trend_radar_search.schemas import QuerySpec, CandidateOverview
    from backend import config
    
    TALENT_SEARCH_AVAILABLE = True
    
except ImportError as e:
    print(f"[WARNING] Talent search module not available: {e}")
    if missing_deps:
        print(f"[INFO] Quick fix: pip install {' '.join(missing_deps)}")
    TALENT_SEARCH_AVAILABLE = False
except Exception as e:
    print(f"[ERROR] Unexpected error loading talent search module: {e}")
    TALENT_SEARCH_AVAILABLE = False

class GlobalTalentManager:
    """全局人才管理器，负责跨方向的人才去重和分配"""
    
    def __init__(self):
        self.talent_pool = {}  # 人才池：{talent_key: talent_data}
        self.direction_assignments = {}  # 方向分配：{direction: [talent_keys]}
        self.talent_to_directions = {}  # 人才到方向的映射：{talent_key: [directions]}
    
    def _generate_talent_key(self, talent: Dict[str, Any]) -> str:
        """为人才生成唯一标识符"""
        # 使用姓名、邮箱等信息生成唯一key
        name = talent.get('title', '').lower().strip()
        email = talent.get('email', '').lower().strip()
        
        # 清理姓名，去除常见前缀和后缀
        name = re.sub(r'\b(dr\.?|prof\.?|professor)\s*', '', name)
        name = re.sub(r'\s+', ' ', name).strip()
        
        if email:
            return f"{name}|{email}"
        elif name:
            return f"{name}|no_email"
        else:
            return f"unknown|{hash(str(talent))}"
    
    def _is_same_person(self, talent1: Dict[str, Any], talent2: Dict[str, Any]) -> bool:
        """判断两个人才记录是否为同一人"""
        name1 = talent1.get('title', '').lower().strip()
        name2 = talent2.get('title', '').lower().strip()
        email1 = talent1.get('email', '').lower().strip()
        email2 = talent2.get('email', '').lower().strip()
        
        # 清理姓名
        name1 = re.sub(r'\b(dr\.?|prof\.?|professor)\s*', '', name1)
        name2 = re.sub(r'\b(dr\.?|prof\.?|professor)\s*', '', name2)
        name1 = re.sub(r'\s+', ' ', name1).strip()
        name2 = re.sub(r'\s+', ' ', name2).strip()
        
        # 如果有邮箱且相同，则为同一人
        if email1 and email2 and email1 == email2:
            return True
        
        # 如果姓名完全相同，需要进一步检查邮箱
        if name1 and name2 and name1 == name2:
            # 如果两个人姓名完全相同，但都有不同的邮箱，则认为是不同人
            if email1 and email2 and email1 != email2:
                return False
            # 如果姓名相同且邮箱相同或至少有一个没有邮箱，则认为是同一人
            return True
        
        # 如果姓名相似度很高，也认为是同一人（但只在邮箱匹配或缺失时）
        if name1 and name2:
            name1_words = set(name1.split())
            name2_words = set(name2.split())
            if len(name1_words) >= 2 and len(name2_words) >= 2:
                overlap = len(name1_words.intersection(name2_words))
                min_words = min(len(name1_words), len(name2_words))
                if overlap >= min_words:  # 所有词都匹配
                    # 只有在邮箱匹配或至少一个邮箱缺失的情况下才认为是同一人
                    if not email1 or not email2 or email1 == email2:
                        return True
        
        return False
    
    def add_talent_to_direction(self, talent: Dict[str, Any], direction: str) -> bool:
        """
        将人才添加到指定方向，如果已存在则跳过
        
        Returns:
            bool: True if added successfully, False if already exists
        """
        talent_key = self._generate_talent_key(talent)
        
        # 检查是否已存在相同的人才
        for existing_key, existing_talent in self.talent_pool.items():
            if self._is_same_person(talent, existing_talent):
                print(f"人才 '{talent.get('title', 'Unknown')}' 已存在，跳过重复添加 (现有方向: {self.talent_to_directions.get(existing_key, [])})")
                return False
        
        # 添加新人才
        self.talent_pool[talent_key] = talent
        
        # 记录方向分配
        if direction not in self.direction_assignments:
            self.direction_assignments[direction] = []
        self.direction_assignments[direction].append(talent_key)
        
        # 记录人才到方向的映射
        if talent_key not in self.talent_to_directions:
            self.talent_to_directions[talent_key] = []
        self.talent_to_directions[talent_key].append(direction)
        
        print(f"[GlobalTalentManager] Added talent '{talent.get('title', 'Unknown')}' to direction '{direction}'")
        return True
    
    def get_direction_talents(self, direction: str) -> List[Dict[str, Any]]:
        """获取指定方向的人才列表"""
        talent_keys = self.direction_assignments.get(direction, [])
        return [self.talent_pool[key] for key in talent_keys if key in self.talent_pool]
    
    def get_total_unique_talents(self) -> int:
        """获取全局唯一人才总数"""
        return len(self.talent_pool)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取人才统计信息"""
        return {
            "total_unique_talents": len(self.talent_pool),
            "directions_count": len(self.direction_assignments),
            "direction_assignments": {
                direction: len(talents) 
                for direction, talents in self.direction_assignments.items()
            }
        }


class TrendTalentSearcher:
    """Trend Radar talent searcher"""
    
    def __init__(self):
        self.available = TALENT_SEARCH_AVAILABLE
        self.global_manager = GlobalTalentManager()  # 全局人才管理器
        if not self.available:
            print("[WARNING] Talent search functionality unavailable - will return empty results")
    
    def search_by_names(self, names: List[str], api_key: str = None, max_per_name: int = 1) -> List[Dict[str, Any]]:
        """
        从推文获取的人才名字进行搜索
        跳过前期搜索步骤，直接从 OpenReview 等学术数据源开始构建 profile
        """
        if not self.available:
            print("Talent search功能不可用，返回空结果")
            return []
        
        out = []
        print(f"开始按姓名搜索 {len(names)} 位人才...")
        print(f"搜索策略: 直接从学术数据源(OpenReview等)构建profile，跳过前期搜索")
            
        for name in names:
            # 如果已经找到足够的人才，停止搜索
            if len(out) >= max_per_name:
                print(f"已达到目标数量 {max_per_name}，停止搜索")
                break
                
            try:
                print(f"\n   正在搜索: {name}")

                # 直接调用 orchestrate_candidate_report —— 跳过前期搜索步骤
                from backend.trend_radar_search.author_discovery import orchestrate_candidate_report

                profile, overview, eval_res = orchestrate_candidate_report(
                    first_author=name,
                    paper_title="",           # 没有论文标题
                    paper_url=None,
                    aliases=[],               # 没有别名
                    k_queries=10,             # 适度的查询数量
                    author_id=None,
                    api_key=api_key,
                    use_lightweight_mode=True  # 使用轻量级模式，提高速度
                )

                # 完全信任 Targeted Search 的内部过滤逻辑
                if overview is None:
                    print(f"   ❌ {name} 未找到OpenReview档案（已被Targeted Search内部过滤）")
                    continue

                formatted = self._format_candidate(overview, name)
                
                # 🔧 修复：将格式化后的候选人添加到结果列表
                if formatted:
                    out.append(formatted)
                    print(f"   ✅ {name} 搜索成功，评分: {formatted.get('total_score', 0)}/35")
                else:
                    print(f"   ⚠️ {name} 格式化失败")

            except Exception as e:
                print(f"   ❌ {name} 搜索失败: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print(f"\n姓名搜索完成，找到 {len(out)} 位合格人才")
        return out
    
    def search_talents_for_direction(self, 
                                    direction_title: str,
                                    direction_content: str = "",
                                    max_candidates: int = 3,
                                    api_key: str = None) -> List[Dict[str, Any]]:
        """
        为研究方向搜索人才，走 Targeted Search 全流程
        跳过意图识别步骤，直接用方向文本与会议、年份拼接进行搜索
        """
        if not self.available:
            print("Talent search功能不可用，返回空结果")
            return []
        
        # 直接拼接方向标题和内容作为查询
        query_text = f"{direction_title}".strip()
        
        if not query_text:
            print("查询文本为空")
            return []
        
        print(f"\n开始为方向搜索人才: '{direction_title}'")
        print(f"查询文本: {query_text[:100]}...")
        
        try:
            # keywords: 直接使用方向文本，不进行意图识别拆分
            # venues/years: 空列表让 Targeted Search 自动推断和拼接
            spec = QuerySpec(
                top_n=max_candidates,
                keywords=[query_text],    # 直接整句，跳过意图识别
                venues=[],                 # TS 会自动推断相关会议并拼接
                years=[],                  # TS 会自动选择年份范围并拼接
                must_be_current_student=False,  # 趋势人才不限学生身份
                degree_levels=["PhD", "Master", "Postdoc"],  # 可招聘层次
                author_priority=["first"]  # 聚焦主要贡献者
            )

            # 调用 Targeted Search 全流程
            # 内部会自动：拼接会议 + 年份 → 搜索 → 筛选 → 提取 → 评分 → 排序
            print(f"调用 Targeted Search 全流程...")
            search_results = agent_execute_search(spec, api_key=api_key)
            
            # search_results 是 SearchResults 对象，包含 recommended_candidates
            cand_list = search_results.recommended_candidates
            print(f"Targeted Search 返回 {len(cand_list)} 位推荐候选人")

            # 不额外评分过滤，完全信任 Targeted Search 的排序结果
            # Targeted Search 内部已经过滤和排序，recommended_candidates 就是最佳结果
            formatted = []
            for c in cand_list:
                candidate = self._format_candidate(c, direction_title)
                if candidate:
                    formatted.append(candidate)
                    print(f"      {c.name}")
                    print(f"      评分: {c.total_score}/35")
                    print(f"      机构: {c.current_role_affiliation or 'Unknown'}")

            # 全局去重（使用 GlobalTalentManager）
            assigned = []
            for f in formatted:
                if len(assigned) >= max_candidates:
                    break
                if self.global_manager.add_talent_to_direction(f, direction_title):
                    assigned.append(f)
            
            print(f"[Direction Search] '{direction_title}' final assignment: {len(assigned)} talents")
            return assigned
            
        except Exception as e:
            print(f"[Direction Search] Failed: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    
    def _format_candidate(self, candidate: 'CandidateOverview', direction_title: str) -> Dict[str, Any]:
        """格式化候选人数据"""
        try:
            # 转换为字典 - 兼容 Pydantic 和 dataclass
            if hasattr(candidate, 'model_dump'):
                # Pydantic v2
                candidate_dict = candidate.model_dump()
            elif hasattr(candidate, 'dict'):
                # Pydantic v1
                candidate_dict = candidate.dict()
            elif hasattr(candidate, '__dataclass_fields__'):
                # dataclass
                candidate_dict = asdict(candidate)
            else:
                # 直接访问属性
                candidate_dict = {
                    'name': getattr(candidate, 'name', 'Unknown'),
                    'current_affiliation': getattr(candidate, 'current_affiliation', ''),
                    'current_role_affiliation': getattr(candidate, 'current_role_affiliation', ''),
                    'research_interests': getattr(candidate, 'research_interests', []),
                    'research_keywords': getattr(candidate, 'research_keywords', []),
                    'research_focus': getattr(candidate, 'research_focus', []),
                    'notable_papers': getattr(candidate, 'notable_papers', []),
                    'representative_papers': getattr(candidate, 'representative_papers', []),
                    'top_tier_hits': getattr(candidate, 'top_tier_hits', []),
                    'publication_overview': getattr(candidate, 'publication_overview', []),
                    'honors_grants': getattr(candidate, 'honors_grants', []),
                    'service_talks': getattr(candidate, 'service_talks', []),
                    'open_source_projects': getattr(candidate, 'open_source_projects', []),
                    'profiles': getattr(candidate, 'profiles', {}),
                    'radar': getattr(candidate, 'radar', {}),
                    'total_score': getattr(candidate, 'total_score', 0),
                    'detailed_scores': getattr(candidate, 'detailed_scores', {}),
                    'email': getattr(candidate, 'email', ''),
                    'current_status': getattr(candidate, 'current_status', ''),
                    'highlights': getattr(candidate, 'highlights', []),
                }
            
            # 提取关键信息
            name = candidate_dict.get('name', 'Unknown Researcher')
            current_affiliation = candidate_dict.get('current_affiliation', 'Research Institution')
            
            # 构建更详细的描述
            research_interests = candidate_dict.get('research_interests', [])
            research_keywords = candidate_dict.get('research_keywords', [])
            research_focus = candidate_dict.get('research_focus', [])
            
            description_parts = []
            
            # 研究兴趣和关键词
            all_interests = list(set(research_interests + research_keywords + research_focus))
            if all_interests:
                description_parts.append(f"Research focus: {', '.join(all_interests[:5])}")
            
            # 学术产出
            notable_papers = candidate_dict.get('notable_papers', [])
            representative_papers = candidate_dict.get('representative_papers', [])
            top_tier_hits = candidate_dict.get('top_tier_hits', [])
            
            all_papers = notable_papers + representative_papers + top_tier_hits
            if all_papers:
                paper_count = len(all_papers)
                description_parts.append(f"Academic output: {paper_count} notable publications")
                
                # 如果有顶级期刊/会议论文，特别标注
                if top_tier_hits:
                    description_parts.append(f"Published in {len(top_tier_hits)} top-tier venues")
            
            # 荣誉和资助
            honors_grants = candidate_dict.get('honors_grants', [])
            if honors_grants:
                description_parts.append(f"Honors & grants: {len(honors_grants)} awards/funding")
            
            # 学术服务和演讲
            service_talks = candidate_dict.get('service_talks', [])
            if service_talks:
                description_parts.append(f"Academic service: {len(service_talks)} talks/service roles")
            
            # 开源项目
            open_source_projects = candidate_dict.get('open_source_projects', [])
            if open_source_projects:
                description_parts.append(f"Open source: {len(open_source_projects)} projects")
            
            # 学术档案
            profiles = candidate_dict.get('profiles', {})
            if profiles:
                profile_types = [k for k in profiles.keys() if profiles[k]]
                if profile_types:
                    description_parts.append(f"Academic profiles: {', '.join(profile_types[:3])}")
            
            # 生成更完善的综合描述
            if description_parts:
                description = '. '.join(description_parts) + '.'
            else:
                # 如果没有详细信息，尝试从可用数据生成基础描述
                description = f"Researcher working on {direction_title}"
                if current_affiliation and current_affiliation != 'Research Institution':
                    description += f" at {current_affiliation}"
            
            # 确保描述的专业性和完整性
            if not description.endswith('.'):
                description += '.'
            
            # 直接使用 Targeted Search 计算的总分，不重新计算
            # CandidateOverview 已经包含了 total_score（通过 evaluate_profile_7d 计算）
            total_score = candidate_dict.get('total_score', 0)
            
            # 获取radar数据（已由 Targeted Search 生成）
            radar = candidate_dict.get('radar', {})
            
            # 提取完整的学术信息
            publication_overview = candidate_dict.get('publication_overview', [])
            top_tier_hits = candidate_dict.get('top_tier_hits', [])
            honors_grants = candidate_dict.get('honors_grants', [])
            service_talks = candidate_dict.get('service_talks', [])
            open_source_projects = candidate_dict.get('open_source_projects', [])
            representative_papers = candidate_dict.get('representative_papers', [])
            highlights = candidate_dict.get('highlights', [])
            
            # 如果某些字段为空，尝试从其他字段推导和增强
            if not publication_overview and notable_papers:
                publication_overview = [f"Published {len(notable_papers)} notable papers in relevant areas"]
            
            if not highlights:
                # 生成更丰富、更专业的亮点信息
                highlight_parts = []
                
                # 研究专长亮点
                if all_interests:
                    expertise_areas = ', '.join(all_interests[:3])
                    highlight_parts.append(f"Research expertise in {expertise_areas}")
                
                # 学术成果亮点
                if top_tier_hits:
                    venue_count = len(top_tier_hits)
                    if venue_count > 1:
                        highlight_parts.append(f"Published {venue_count} papers in top-tier conferences/journals")
                    else:
                        highlight_parts.append("Published in top-tier academic venues")
                elif all_papers:
                    highlight_parts.append(f"Author of {len(all_papers)} research publications")
                
                # 学术荣誉亮点
                if honors_grants:
                    award_count = len(honors_grants)
                    if award_count > 1:
                        highlight_parts.append(f"Recipient of {award_count} academic awards/grants")
                    else:
                        highlight_parts.append("Recognized with academic honors and grants")
                
                # 技术贡献亮点
                if open_source_projects:
                    project_count = len(open_source_projects)
                    if project_count > 1:
                        highlight_parts.append(f"Contributor to {project_count} open source projects")
                    else:
                        highlight_parts.append("Active contributor to open source research community")
                
                # 学术服务亮点
                if service_talks:
                    service_count = len(service_talks)
                    if service_count > 2:
                        highlight_parts.append(f"Active in academic service with {service_count} talks/roles")
                    else:
                        highlight_parts.append("Engaged in academic community service")
                
                # 如果还是没有亮点，生成基于职位和机构的亮点
                if not highlight_parts:
                    if current_status and current_status != 'Researcher':
                        highlight_parts.append(f"{current_status} specializing in {direction_title}")
                    else:
                        highlight_parts.append(f"Researcher working on {direction_title}")
                    
                    if current_affiliation and current_affiliation != 'Research Institution':
                        highlight_parts.append(f"Affiliated with {current_affiliation}")
                
                highlights = highlight_parts
            
            # 补充缺失的研究状态信息
            current_status = candidate_dict.get('current_status', '')
            if not current_status:
                if 'phd' in description.lower() or 'doctoral' in description.lower():
                    current_status = 'PhD Candidate'
                elif 'professor' in current_affiliation.lower() or 'prof' in current_affiliation.lower():
                    current_status = 'Professor'
                elif 'postdoc' in description.lower() or 'postdoctoral' in description.lower():
                    current_status = 'Postdoctoral Researcher'
                else:
                    current_status = 'Researcher'

            return {
                'title': name,
                'content': description,
                'affiliation': current_affiliation,
                'status': current_status,
                'total_score': total_score,  # 使用 Targeted Search 的评分（满分35）
                'profiles': profiles,
                'research_interests': research_interests,
                'notable_papers': notable_papers[:3],  # 限制论文数量
                'radar': radar,
                # 新增详细学术信息字段
                'publication_overview': publication_overview,
                'top_tier_hits': top_tier_hits,
                'honors_grants': honors_grants,
                'service_talks': service_talks,
                'open_source_projects': open_source_projects,
                'representative_papers': representative_papers,
                'highlights': highlights,
                'email': candidate_dict.get('email', ''),
                'current_role_affiliation': candidate_dict.get('current_role_affiliation', current_affiliation),
                'current_status': candidate_dict.get('current_status', 'Researcher'),
                'research_keywords': candidate_dict.get('research_keywords', research_interests),
                'research_focus': candidate_dict.get('research_focus', research_interests),
                'detailed_scores': candidate_dict.get('detailed_scores', {}),
            }
            
        except Exception as e:
            print(f"格式化候选人失败: {e}")
            return None
    
    def _looks_like_person_name(self, name: str) -> bool:
        """
        检查字符串是否像人名（初步检查）
        """
        if not name or len(name) < 3:
            return False
        
        # 排除明显不是人名的模式
        non_person_indicators = [
            'research', 'university', 'institute', 'center', 'lab', 'group',
            'department', 'school', 'college', 'conference', 'workshop',
            'journal', 'publication', 'paper', 'study', 'analysis',
            'autonomous', 'artificial', 'machine', 'deep', 'neural',
            'learning', 'intelligence', 'system', 'algorithm', 'method'
        ]
        
        name_lower = name.lower()
        if any(indicator in name_lower for indicator in non_person_indicators):
            return False
        
        # 检查是否包含典型的人名词汇
        words = name.split()
        if len(words) < 2 or len(words) > 4:
            return False
        
        # 每个词都应该像姓名
        for word in words:
            if not word[0].isupper() or not word[1:].islower():
                return False
            if len(word) < 2:
                return False
        
        return True
    
    def _llm_verify_person_name(self, name: str, snippet: str = "", api_key: str = None) -> bool:
        """
        使用LLM验证姓名是否为真实人名（参考targeted search逻辑）
        """
        try:
            # 如果姓名明显不是人名，跳过LLM验证以节省token
            if not self._is_valid_person_name(name):
                return False
            
            # 构建验证prompt
            prompt = f"""You are a strict name validator. Determine if the following is a REAL PERSON'S NAME (not a concept, organization, or technology).
            Target Name: "{name}"
            Context: {snippet[:200] if snippet else "No additional context"}
            Requirements:
            1. Must be a human person's actual name (first/last name combination)
            2. NOT a technology, concept, organization, or project name
            3. NOT a company, university, or institution name
            4. NOT an AI model, algorithm, or system name
            5. NOT a research paper title or academic concept
            Examples of VALID names: "John Smith", "Dr. Maria Garcia", "Prof. Alan Turing"
            Examples of INVALID names: "Machine Learning", "Stanford University", "Deep Learning Model", "Research Group", "AI System"
            Is "{name}" a real person's name?
            Respond with only: YES or NO"""

            from backend import llm as llm_utils
            llm = llm_utils.get_llm(role="talent_verification", temperature=0.1, api_key=api_key)
            response = llm.invoke(prompt, enable_thinking=False)
            
            if response and isinstance(response, str):
                return response.strip().upper() == "YES"
            
        except Exception as e:
            print(f"[LLM验证] 验证姓名 '{name}' 失败: {e}")
        
        # 如果LLM验证失败，回退到传统验证
        return self._is_valid_person_name(name)
    
    def _needs_llm_verification(self, name: str, title: str, snippet: str) -> bool:
        """
        判断是否需要LLM验证（为节省token，只对可疑情况进行验证）
        """
        # 将名称、标题和片段转为小写进行检查
        name_lower = name.lower()
        title_lower = title.lower()
        snippet_lower = snippet.lower()
        
        # 可疑指示器：如果包含这些，需要LLM验证
        suspicious_indicators = [
            # 技术术语在姓名中
            'ai', 'ml', 'deep', 'neural', 'learning', 'intelligence', 'computing',
            'research', 'system', 'method', 'model', 'algorithm', 'framework',
            
            # 标题中包含非个人指示器
            'powered by', 'developed by', 'created by', 'team', 'group', 'lab',
            'project', 'initiative', 'program', 'platform', 'tool', 'software',
            
            # 可疑的名称模式
            'multimodal', 'autonomous', 'intelligent', 'smart', 'automated',
            'cognitive', 'computational', 'analytical', 'predictive'
        ]
        
        # 检查名称本身是否包含可疑指示器
        for indicator in suspicious_indicators:
            if indicator in name_lower:
                return True
        
        # 检查标题是否包含可疑模式但名称看起来可能是人名
        title_suspicious_patterns = [
            'powered', 'system', 'tool', 'platform', 'method', 'approach',
            'framework', 'solution', 'technology', 'innovation', 'research group'
        ]
        
        for pattern in title_suspicious_patterns:
            if pattern in title_lower:
                return True
        
        # 检查URL是否指向非个人页面
        # 这里可以添加URL检查逻辑
        
        # 如果姓名是两个单词且第一个单词可能是技术术语
        words = name.split()
        if len(words) == 2:
            first_word = words[0].lower()
            tech_terms = [
                'data', 'cloud', 'edge', 'quantum', 'cyber', 'digital', 'smart',
                'auto', 'robo', 'meta', 'super', 'ultra', 'hyper', 'multi'
            ]
            if first_word in tech_terms:
                return True
        
        # 默认不需要LLM验证（节省token）
        return False
    
    def _is_valid_person_name(self, name: str) -> bool:
        """
        严格验证是否为有效的人名
        """
        if not name or len(name.strip()) < 3:
            return False
        
        name = name.strip()
        
        # 定义明显的非人名指示词（大幅扩展版本，参考targeted search）
        non_person_keywords = {
            # 研究机构和组织
            'autonomous research', 'artificial intelligence', 'machine learning',
            'deep learning', 'neural network', 'computer vision', 'natural language',
            'data science', 'research center', 'research institute', 'research lab',
            'research group', 'university', 'institute', 'center', 'laboratory',
            'department', 'school', 'college', 'division', 'faculty', 'staff',
            
            # 技术和方法名称
            'transformer', 'attention mechanism', 'reinforcement learning',
            'supervised learning', 'unsupervised learning', 'federated learning',
            'transfer learning', 'meta learning', 'few shot learning',
            'zero shot learning', 'multi agent', 'multi-agent', 'neural networks',
            'computer science', 'machine intelligence', 'robotics', 'nlp', 'cv',
            
            # 会议和期刊
            'conference', 'workshop', 'symposium', 'journal', 'proceedings',
            'transactions', 'letters', 'review', 'survey', 'lecture', 'seminar',
            
            # 项目和产品名称
            'project', 'system', 'framework', 'platform', 'toolkit',
            'library', 'package', 'software', 'application', 'solution',
            'database', 'dataset', 'benchmark', 'corpus', 'api', 'tool',
            
            # 其他明显非人名
            'research', 'study', 'analysis', 'evaluation', 'assessment',
            'methodology', 'approach', 'technique', 'algorithm', 'model',
            'tutorial', 'guide', 'documentation', 'manual', 'handbook',
            'introduction', 'overview', 'news', 'article', 'blog', 'post',
            
            # 常见的错误匹配词汇（targeted search发现的）
            'powered multimodal', 'member profiles', 'how to write',
            'mobility after', 'specialty profiles', 'powered by',
            'patient ai', 'profiles research', 'after ai',
            'multimodal patient', 'write research', 'research institution',
            'artificial general', 'computational biology', 'quantum computing',
            'autonomous systems', 'intelligent systems', 'cognitive science',
            
            # 新增：更多常见非人名模式（来自targeted search的经验）
            'startup', 'company', 'organization', 'foundation', 'society',
            'collaboration', 'partnership', 'network', 'initiative', 'program',
            'curriculum', 'course', 'training', 'education', 'teaching',
            'publication', 'paper', 'thesis', 'dissertation', 'report',
            'announcement', 'call for papers', 'submission', 'deadline',
            'scientific', 'academic', 'technological', 'innovation',
            'development', 'engineering', 'mathematics', 'statistics',
            'dataset collection', 'data mining', 'big data', 'cloud computing',
            'edge computing', 'blockchain', 'cryptocurrency', 'fintech',
            'biotech', 'medtech', 'healthtech', 'edtech', 'cleantech',
            
            # 特定错误案例（基于实际观察）
            'how to build', 'what is the', 'introduction to', 'overview of',
            'a survey of', 'state of the art', 'cutting edge', 'breakthrough',
            'novel approach', 'new method', 'latest research', 'recent advances',
            'future directions', 'open challenges', 'current trends',
        }
        
        name_lower = name.lower()
        
        # 检查是否包含明显的非人名关键词
        if any(keyword in name_lower for keyword in non_person_keywords):
            return False
        
        # 检查是否为全大写（通常不是人名）
        if name.isupper() and len(name) > 10:
            return False
        
        # 检查单词数量（人名通常是2-4个单词）
        words = name.split()
        if len(words) < 2 or len(words) > 4:
            return False
        
        # 检查每个单词是否符合人名格式
        valid_name_words = 0
        for word in words:
            # 去除标点符号
            clean_word = re.sub(r'[^\w]', '', word)
            
            if not clean_word:
                continue
            
            # 人名单词通常首字母大写，后面小写，长度合理
            if len(clean_word) < 2 or len(clean_word) > 15:
                return False
            
            # 检查是否包含数字（人名通常不包含数字）
            if any(c.isdigit() for c in clean_word):
                return False
            
            # 检查首字母大写（除了连接词）
            if clean_word.lower() not in ['de', 'van', 'von', 'la', 'le', 'du', 'del', 'della', 'di']:
                if not clean_word[0].isupper():
                    return False
                # 检查是否有小写字母（避免全大写的缩写词）
                if not any(c.islower() for c in clean_word[1:]):
                    return False
                valid_name_words += 1
        
        # 至少需要有2个有效的人名单词
        if valid_name_words < 2:
            return False
        
        # 额外检查：是否包含常见的学术术语模式（排除常见的人名前缀）
        academic_patterns = [
            r'\b(?:et\s+al|PhD|Professor|Research|Study|Analysis)\b',
            r'\b(?:Learning|Network|System|Method|Algorithm|Model)\b',
            r'\b(?:Conference|Workshop|Journal|Proceedings)\b'
        ]
        
        # 允许Dr.作为人名前缀，但排除其他学术术语
        name_without_dr = re.sub(r'\bDr\.?\s*', '', name, flags=re.IGNORECASE)
        for pattern in academic_patterns:
            if re.search(pattern, name_without_dr, re.IGNORECASE):
                return False
        
        return True
    
    

# 全局实例
trend_talent_searcher = TrendTalentSearcher()

# ==================== 便捷函数（模块导出接口） ====================

def search_talents_for_direction(direction_title: str, 
                               direction_content: str = "",
                               max_candidates: int = 3,
                               api_key: str = None) -> List[Dict[str, Any]]:
    """为研究方向搜索人才的便捷函数"""
    return trend_talent_searcher.search_talents_for_direction(
        direction_title, direction_content, max_candidates, api_key
    )

def search_talents_by_names(names: List[str], max_per_name: int = 1, api_key: str = None) -> List[Dict[str, Any]]:
    """根据姓名列表搜索人才的便捷函数"""
    return trend_talent_searcher.search_by_names(names, api_key=api_key, max_per_name=max_per_name)

def search_talents_with_fallback(generated_names: List[str], 
                                direction_title: str,
                                direction_content: str = "",
                                api_key: str = None) -> List[Dict[str, Any]]:
    """
    智能人才搜索：优先搜索AI生成的人才姓名，不足时用方向搜索补齐
    
    Args:
        generated_names: AI生成的人才姓名列表
        direction_title: 研究方向标题
        direction_content: 方向描述
        api_key: API密钥
    
    Returns:
        人才列表
    """
    # 先按姓名搜索
    talents_from_names = trend_talent_searcher.search_by_names(
        names=generated_names,
        api_key=api_key,
        max_per_name=len(generated_names)
    )
    
    # 如果不足3个，用方向搜索补齐
    if len(talents_from_names) < 3:
        needed = 3 - len(talents_from_names)
        talents_from_direction = trend_talent_searcher.search_talents_for_direction(
            direction_title=direction_title,
            direction_content=direction_content,
            max_candidates=needed,
            api_key=api_key
        )
        
        # 合并并去重
        existing_names = {t.get('title', '').lower() for t in talents_from_names}
        for talent in talents_from_direction:
            if talent.get('title', '').lower() not in existing_names:
                talents_from_names.append(talent)
    
    return talents_from_names

def search_talents_for_multiple_directions(directions: List[Dict[str, str]], 
                                         max_candidates_per_direction: int = 3,
                                         api_key: str = None) -> Dict[str, List[Dict[str, Any]]]:
    """批量搜索多个方向人才的便捷函数（带全局去重）"""
    return trend_talent_searcher.search_talents_for_multiple_directions(
        directions, max_candidates_per_direction, api_key
    )

def get_talent_statistics() -> Dict[str, Any]:
    """获取人才搜索统计信息的便捷函数"""
    return trend_talent_searcher.get_talent_statistics()

def reset_talent_search_session():
    """重置人才搜索会话的便捷函数"""
    trend_talent_searcher.reset_talent_manager()