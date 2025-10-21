import streamlit as st
import json
import pandas as pd
import plotly.graph_objects as go
import html as _html
from pathlib import Path
import sys
import time
import os
import textwrap

# Import the backend module
try:
    from backend.reports import build_achievement_report, generate_group_achievement_report
    from backend.report_storage import save_achievement_report, load_achievement_reports, delete_report, get_storage_stats
    backend_available = True
except ImportError as e:
    print(f"Achievement Report ImportError: {e}")
    backend_available = False

# Default groups data
DEFAULT_GROUPS = {
    "recommend_research_group": {
        "name": "Recommend Research Group",
        "storage_type": "recommend_research_group",  # Storage directory mapping
        "members": [
            {
                "name": "Lexin Zhou",
                "homepage": "https://lexzhou.github.io/",
                "affiliation": "1st-year CS PhD candidate at Princeton University, advised by Prof. Peter Henderson at the POLARIS Lab"
            },
            {
                "name": "Zhongzhi Li",
                "homepage": "https://zzli2022.github.io/",
                "affiliation": "Researcher in Artificial Intelligence"
            },
            {
                "name": "Ziming Liu",
                "homepage": "https://kindxiaoming.github.io/",
                "affiliation": "Postdoc at Stanford & Enigma, working with Prof. Andreas Tolias; PhD from MIT advised by Prof. Max Tegmark"
            },
        ],
        "description": "Researchers working on AI, computational social science, NLP, and agent simulation",
        "color": "#92ac2e"
    },
    "demo_research_group": {
        "name": "MSRA former interns",
        "storage_type": "msra_former_interns",  # Storage directory mapping
        "members": [
            {
                "name": "Lexin Zhou",
                "homepage": "https://lexzhou.github.io/",
                "affiliation": "1st-year CS PhD candidate at Princeton University, advised by Prof. Peter Henderson at the POLARIS Lab"
            },
            {
                "name": "Zhongzhi Li",
                "homepage": "https://zzli2022.github.io/",
                "affiliation": "Researcher in Artificial Intelligence"
            },
            {
                "name": "Ziming Liu",
                "homepage": "https://kindxiaoming.github.io/",
                "affiliation": "Postdoc at Stanford & Enigma, working with Prof. Andreas Tolias; PhD from MIT advised by Prof. Max Tegmark"
            },
            {
                "name": "Jinsook Lee",
                "homepage": "https://jinsook-jennie-lee.github.io/",
                "affiliation": "Ph.D. candidate, Information Science, Cornell University"
            },
            {
                "name": "Zengqing Wu",
                "homepage": "https://wuzengqing001225.github.io/",
                "affiliation": "Master's student, Graduate School of Informatics, Kyoto University; Research Associate, Osaka University"
            },
            {
                "name": "Xinyi Mou",
                "homepage": "https://xymou.github.io/",
                "affiliation": "Ph.D. student, Fudan University (Data Intelligence and Social Computing Lab)"
            },
            {
                "name": "Jiarui Ji",
                "homepage": "https://ji-cather.github.io/homepage/",
                "affiliation": "M.E. student, Gaoling School of Artificial Intelligence, Renmin University of China"
            }
        ],
        "description": "Researchers working on AI, computational social science, NLP, and agent simulation",
        "color": "#4facfe"
    },
    "StartTrack": {
        "name": "StartTrack Group",
        "storage_type": "starttrack_group",  # Storage directory mapping
        "members": [
            {
                "name": "Lexin Zhou",
                "homepage": "https://lexzhou.github.io/",
                "affiliation": "1st-year CS PhD candidate at Princeton University, advised by Prof. Peter Henderson at the POLARIS Lab"
            },
            {
                "name": "Ziming Liu",
                "homepage": "https://kindxiaoming.github.io/",
                "affiliation": "Postdoc at Stanford & Enigma, working with Prof. Andreas Tolias; PhD from MIT advised by Prof. Max Tegmark"
            },
        ],
        "description": "Researchers working on AI, computational social science, NLP, and agent simulation",
        "color": "#3fac3e"
    }
}

def load_groups():
    """Load groups from session state or use defaults"""
    if "achievement_groups" not in st.session_state:
        st.session_state.achievement_groups = DEFAULT_GROUPS.copy()
    return st.session_state.achievement_groups

def save_groups(groups):
    """Save groups to session state"""
    st.session_state.achievement_groups = groups

def render_research_groups_page():
    """Render the main research groups page"""

    # Check backend module status (silent)
    if not backend_available:
        st.warning("⚠️ Backend module not available. Using mock data mode.")

    # Action buttons row
    col_actions1, col_actions2 = st.columns(2)

    with col_actions1:
        if st.button("➕ Create New Group", key="create_new_group_unique_test", type="primary", use_container_width=True):
            st.session_state.current_page = "edit_group"
            st.session_state.editing_group = None
            # Force clear any cached state and rerun
            st.session_state.page_changed = True
            st.rerun()

    with col_actions2:
        if st.button("📋 View Existing Reports", key="view_existing_reports_unique_test", type="primary", use_container_width=True):
            st.session_state.current_page = "view_reports"
            # Force clear any cached state and rerun
            st.session_state.page_changed = True
            st.rerun()

    st.markdown("---")

    # Load and display groups
    groups = load_groups()
    
    # Groups grid layout
    st.markdown("### 🎯 Research Groups")
    
    # Create a responsive grid layout
    group_ids = list(groups.keys())
    num_groups = len(group_ids)
    
    # Calculate optimal grid layout
    if num_groups <= 3:
        cols = st.columns(num_groups)
    elif num_groups <= 6:
        cols = st.columns(3)
    else:
        cols = st.columns(4)
    
    for i, group_id in enumerate(group_ids):
        group_data = groups[group_id]
        col_idx = i % len(cols)
        
        with cols[col_idx]:
            # Group card
            st.markdown(f"""
            <div style="
                background: linear-gradient(135deg, {group_data['color']}15 0%, {group_data['color']}05 100%);
                border: 2px solid {group_data['color']};
                border-radius: 15px;
                padding: 1.5rem;
                margin: 1rem 0;
                transition: all 0.3s ease;
                box-shadow: 0 4px 15px rgba(0,0,0,0.1);
            ">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                    <h3 style="margin: 0; color: {group_data['color']}; font-size: 1.3rem;">{group_data['name']}</h3>
                    <div style="
                        background: {group_data['color']};
                        color: white;
                        padding: 0.3rem 0.8rem;
                        border-radius: 20px;
                        font-size: 0.8rem;
                        font-weight: bold;
                    ">
                        {len(group_data['members'])} members
                    </div>
                </div>
                <p style="margin: 0 0 1rem 0; color: #666; font-size: 0.9rem;">{group_data['description']}</p>
                <div style="display: flex; flex-wrap: wrap; gap: 0.5rem; margin-bottom: 1rem;">
            """, unsafe_allow_html=True)
            
            # Show first 3 members as preview
            for member in group_data['members'][:3]:
                st.markdown(f"""
                <div style="
                    background: {group_data['color']}20;
                    border: 1px solid {group_data['color']}40;
                    padding: 0.3rem 0.6rem;
                    border-radius: 12px;
                    font-size: 0.8rem;
                    color: {group_data['color']};
                ">
                    {member['name']}
                </div>
                """, unsafe_allow_html=True)
            
            if len(group_data['members']) > 3:
                st.markdown(f"""
                <div style="
                    background: {group_data['color']}20;
                    border: 1px solid {group_data['color']}40;
                    padding: 0.3rem 0.6rem;
                    border-radius: 12px;
                    font-size: 0.8rem;
                    color: {group_data['color']};
                ">
                    +{len(group_data['members']) - 3} more
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown("</div></div>", unsafe_allow_html=True)
            
            # Action buttons for each group
            col_btn1, col_btn2 = st.columns(2)
            with col_btn1:
                if st.button("✏️ Edit", key=f"edit_{group_id}", use_container_width=True):
                    st.session_state.current_page = "edit_group"
                    st.session_state.editing_group = group_id
                    st.rerun()

            with col_btn2:
                if st.button("📊 Generate Report", key=f"report_{group_id}", use_container_width=True):
                    st.session_state.current_page = "generate_report"
                    st.session_state.selected_group = group_id
                    # Force clear any cached state and rerun
                    st.session_state.page_changed = True
                    st.rerun()

def render_edit_group_page():
    """Render the edit group page"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_edit", type="secondary"):
        st.session_state.current_page = "research_groups"
        st.session_state.page_changed = True
        st.rerun()

    # Page header
    is_edit = st.session_state.get('editing_group') is not None
    if is_edit:
        st.markdown("### ✏️ Edit Research Group")
    else:
        st.markdown("### ➕ Create New Research Group")
    
    # Load groups
    groups = load_groups()
    editing_group_id = st.session_state.get('editing_group')
    
    if editing_group_id and editing_group_id in groups:
        group_data = groups[editing_group_id]
    else:
        group_data = {
            'name': '',
            'description': '',
            'color': '#667eea',
            'members': []
        }
    
    # Group basic info
    st.markdown("#### 📝 Group Information")
    
    col_info1, col_info2 = st.columns(2)
    with col_info1:
        group_name = st.text_input("Group Name", value=group_data.get('name', ''), key="edit_group_name")
    with col_info2:
        available_colors = ["#667eea", "#764ba2", "#4facfe", "#00f2fe", "#f093fb", "#f5576c"]
        selected_color = st.selectbox("Group Color", available_colors, 
                                    index=available_colors.index(group_data.get('color', '#667eea')) if group_data.get('color') in available_colors else 0, 
                                    key="edit_group_color")
    
    group_description = st.text_area("Description", value=group_data.get('description', ''), 
                                    height=100, key="edit_group_description")
    
    # Members management
    st.markdown("#### 👥 Group Members")
    
    if "temp_members" not in st.session_state:
        st.session_state.temp_members = group_data.get('members', []).copy()
    
    # Display existing members
    if st.session_state.temp_members:
        # Add headers for member input fields
        col_header1, col_header2, col_header3, col_header4 = st.columns([2, 2.5, 3, 1])
        with col_header1:
            st.markdown("**👤 Name**")
        with col_header2:
            st.markdown("**🔗 Homepage** *(optional)*")
        with col_header3:
            st.markdown("**🏛️ Affiliation** *(optional)*")
        with col_header4:
            st.markdown("**Action**")

        st.markdown("---")

    for i, member in enumerate(st.session_state.temp_members):
        st.markdown(f"**Member {i+1}:**")
        col_member1, col_member2, col_member3, col_member4 = st.columns([2, 2.5, 3, 1])

        with col_member1:
            member_name = st.text_input("Name", value=member.get('name', ''),
                                      key=f"member_name_{i}", label_visibility="collapsed",
                                      placeholder="e.g., John Smith")
        with col_member2:
            member_homepage = st.text_input("Homepage", value=member.get('homepage', ''),
                                          key=f"member_homepage_{i}", label_visibility="collapsed",
                                          placeholder="https://example.com/~john")
        with col_member3:
            member_affiliation = st.text_area("Affiliation", value=member.get('affiliation', ''),
                                             key=f"member_affiliation_{i}", label_visibility="collapsed",
                                             placeholder="e.g., Ph.D. candidate, Information Science, Cornell University\nor\nPostdoc at Stanford & Enigma, working with Prof. Andreas Tolias",
                                             height=60)
        with col_member4:
            if st.button("🗑️", key=f"remove_member_{i}", help="Remove member"):
                st.session_state.temp_members.pop(i)
                st.rerun()

        # Update member data
        st.session_state.temp_members[i] = {
            'name': member_name,
            'homepage': member_homepage,
            'affiliation': member_affiliation
        }
    
    # Add new member
    if st.button("➕ Add Member", key="add_member"):
        st.session_state.temp_members.append({
            'name': '',
            'homepage': '',
            'affiliation': ''
        })
        st.rerun()
    
    st.markdown("---")
    
    # Action buttons
    col_actions1, col_actions2, col_actions3 = st.columns([1, 1, 1])
    
    with col_actions1:
        if st.button("💾 Save", key="save_group", type="primary", use_container_width=True):
            # Validate input
            if not group_name.strip():
                st.error("Group name is required!")
                return

            if not st.session_state.temp_members:
                st.error("Group must have at least one member!")
                return

            # Create/update group
            groups = load_groups()
            if editing_group_id:
                groups[editing_group_id] = {
                    'name': group_name.strip(),
                    'description': group_description.strip(),
                    'color': selected_color,
                    'members': [m for m in st.session_state.temp_members if m['name'].strip()]
                }
            else:
                # Generate new ID
                new_id = f"group_{len(groups) + 1}"
                groups[new_id] = {
                    'name': group_name.strip(),
                    'description': group_description.strip(),
                    'color': selected_color,
                    'members': [m for m in st.session_state.temp_members if m['name'].strip()]
                }

            save_groups(groups)
            st.session_state.temp_members = []
            st.session_state.current_page = "research_groups"
            st.session_state.page_changed = True
            st.rerun()

    with col_actions2:
        if st.button("❌ Cancel", key="cancel_edit", type="secondary", use_container_width=True):
            st.session_state.temp_members = []
            st.session_state.current_page = "research_groups"
            st.session_state.page_changed = True
            st.rerun()
    
    with col_actions3:
        if editing_group_id:
            # Delete group functionality with proper state management
            delete_confirm_key = f"delete_confirm_{editing_group_id}"

            # Initialize delete confirmation state if not exists
            if delete_confirm_key not in st.session_state:
                st.session_state[delete_confirm_key] = False

            # Show delete button first
            if st.button("🗑️ Delete Group", key=f"delete_group_{editing_group_id}", type="secondary", use_container_width=True):
                # Toggle the confirmation state
                st.session_state[delete_confirm_key] = True
                st.rerun()

            # Show confirmation checkbox and final delete button only after initial click
            if st.session_state[delete_confirm_key]:
                st.markdown("---")
                st.markdown("⚠️ **Confirm Group Deletion**")
                st.markdown("*This action cannot be undone.*")

                confirm_delete = st.checkbox("I confirm I want to delete this group", key=f"confirm_checkbox_{editing_group_id}")

                col_confirm1, col_confirm2 = st.columns(2)
                with col_confirm1:
                    if st.button("✅ Yes, Delete Group", type="primary", use_container_width=True):
                        if confirm_delete:
                            try:
                                groups = load_groups()
                                group_name = groups[editing_group_id].get('name', 'Unknown')

                                # Delete the group
                                del groups[editing_group_id]
                                save_groups(groups)

                                # Clear all related state
                                st.session_state.temp_members = []
                                if "editing_group" in st.session_state:
                                    del st.session_state.editing_group
                                st.session_state.current_page = "research_groups"
                                st.session_state.page_changed = True

                                # Clear delete confirmation states
                                st.session_state[delete_confirm_key] = False
                                confirm_checkbox_key = f"confirm_checkbox_{editing_group_id}"
                                if confirm_checkbox_key in st.session_state:
                                    del st.session_state[confirm_checkbox_key]

                                st.success(f"Group '{group_name}' deleted successfully!")
                                st.rerun()
                            except KeyError:
                                st.error("Group not found. It may have already been deleted.")
                                st.session_state[delete_confirm_key] = False
                            except Exception as e:
                                st.error(f"Error deleting group: {str(e)}")
                                st.session_state[delete_confirm_key] = False
                        else:
                            st.warning("Please check the confirmation box to proceed with deletion.")

                with col_confirm2:
                    if st.button("❌ Cancel", key="cancel_delete", type="secondary", use_container_width=True):
                        # Reset confirmation state
                        st.session_state[delete_confirm_key] = False
                        st.rerun()

def render_generate_report_page():
    """Render the generate report page"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_generate", type="secondary"):
        st.session_state.current_page = "research_groups"
        st.session_state.page_changed = True
        st.rerun()
    
    # Load groups
    groups = load_groups()

    if not groups:
        st.warning("No research groups available. Please create a group first.")
        if st.button("Create Group", key="create_group_fallback"):
            st.session_state.current_page = "edit_group"
            st.session_state.page_changed = True
            st.rerun()
        return

    # Check if we have a pre-selected group from the group card
    selected_group = st.session_state.get("selected_group")
    
    if selected_group:
        selected_group_data = groups[selected_group]
        
        # Display selected group info
        st.markdown(f"""
        <div style="
            background: linear-gradient(135deg, {selected_group_data['color']}15 0%, {selected_group_data['color']}05 100%);
            border: 2px solid {selected_group_data['color']};
            border-radius: 15px;
            padding: 1.5rem;
            margin: 1rem 0;
        ">
            <h4 style="margin: 0 0 1rem 0; color: {selected_group_data['color']};">{selected_group_data['name']}</h4>
            <p style="margin: 0 0 1rem 0;">{selected_group_data['description']}</p>
            <p style="margin: 0;"><strong>Members:</strong> {len(selected_group_data['members'])}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Report configuration with enhanced styling
        st.markdown("#### ⚙️ Report Configuration")

        # Configuration cards
        config_col1, config_col2 = st.columns(2)

        with config_col1:
            st.markdown("""
                <h5 style="margin-top: 0;">📋 Report Type</h5>
            """, unsafe_allow_html=True)

            report_type = st.selectbox(
                "Choose report focus:",
                ["Full report", "Recent achievements", "Publication stats", "Collaboration network"],
                key="report_type_select",
                help="Select the type of analysis you want in the report"
            )

            st.markdown("</div>", unsafe_allow_html=True)

        with config_col2:
            st.markdown("""
                <h5 style="margin-top: 0;">⏰ Time Range</h5>
            """, unsafe_allow_html=True)

            time_range = st.selectbox(
                "Select time period:",
                ["Last 6 months", "Last year", "Last 2 years", "All time"],
                key="time_range_select",
                help="Choose the time period for the analysis"
            )

            st.markdown("</div>", unsafe_allow_html=True)

        # Optional query input
        st.markdown("---")
        st.markdown("#### 🔍 Optional Query (Advanced)")
        
        custom_query = st.text_area(
            "Custom analysis query (optional):",
            placeholder="e.g., Focus on recent publications and collaborations, exclude older achievements",
            height=100,
            help="Provide specific instructions for achievement analysis (optional)"
        )
        
        # Additional options
        st.markdown("---")
        st.markdown("### 🚀 Generation Options")

        options_col1, options_col2 = st.columns(2)

        with options_col1:
            include_detailed_analysis = st.checkbox(
                "Include detailed member analysis",
                value=True,
                help="Generate individual analysis for each group member"
            )

        with options_col2:
            save_to_history = st.checkbox(
                "Save to report history",
                value=True,
                help="Store this report for future reference"
            )

        # Preview section
        with st.expander("👀 Preview Configuration", expanded=False):
            st.markdown("**Report Summary:**")
            st.info(f"""
            **Group:** {selected_group_data['name']}
            **Members:** {len(selected_group_data['members'])}
            **Type:** {report_type}
            **Time Range:** {time_range}
            **Custom Query:** {'Yes' if custom_query.strip() else 'No'}
            **Detailed Analysis:** {'Yes' if include_detailed_analysis else 'No'}
            **Save to History:** {'Yes' if save_to_history else 'No'}
            """)


        if st.button("🚀 Generate Group Report", key="generate_group_report", type="primary", use_container_width=True):
            # Check if API key is set (support both new and old session variables)
            api_key_available = (st.session_state.get("llm_api_key", "") or 
                                st.session_state.get("openai_api_key", ""))
            if not api_key_available:
                st.error("⚠️ **API Key Required**")
                st.info("Please enter your API key in the sidebar settings (🛠️ LLM Configuration) to use the AI-powered report generation features.")
                st.stop()
            
            # 🕒 Check for recent reports (within 7 days) before generating new one
            if backend_available:
                try:
                    # Determine storage group type
                    group_type_mapping = {
                        "recommend_research_group": "recommend_research_group",
                        "demo_research_group": "msra_former_interns",  # MSRA former interns
                        "StartTrack": "starttrack_group"  # 正确的组ID映射
                    }
                    storage_group_type = group_type_mapping.get(selected_group, "recommend_research_group")
                    
                    # Load recent reports for this group
                    recent_reports = load_achievement_reports(storage_group_type)
                    
                    # Check if there's a report within the last 7 days
                    from datetime import datetime, timedelta
                    seven_days_ago = datetime.now() - timedelta(days=7)
                    
                    recent_report = None
                    for report in recent_reports:
                        try:
                            # Parse the creation time
                            report_time_str = report.get('created_at', '')
                            if report_time_str:
                                report_time = datetime.fromisoformat(report_time_str.replace('Z', '+00:00'))
                                if report_time.replace(tzinfo=None) > seven_days_ago:
                                    recent_report = report
                                    break
                        except Exception as e:
                            continue  # Skip invalid timestamps
                    
                    # If recent report found, automatically use it
                    if recent_report:
                        report_date = datetime.fromisoformat(recent_report['created_at'].replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M')
                        
                        st.success(f"📅 **使用现有报告** - {report_date} (7天内)")
                        # Automatically navigate to existing report
                        st.session_state.current_view_report = recent_report['data']
                        st.session_state.current_page = "view_single_report"
                        st.session_state.page_changed = True
                        st.rerun()
                        
                except Exception as e:
                    # If checking fails, continue with normal generation
                    st.warning(f"⚠️ 无法检查最近报告: {e}")
                    pass
            
            with st.spinner("🔄 Generating achievement report..."):
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    # Real backend path
                    def _on_progress(evt: str, pct: float):
                        try:
                            status_text.text(f"{evt}…")
                            progress_bar.progress(int(max(0, min(1.0, pct)) * 100))
                        except Exception:
                            pass

                    result = generate_group_achievement_report(
                        members=selected_group_data['members'],
                        api_key=(st.session_state.get("llm_api_key", "") or 
                                st.session_state.get("openai_api_key", "")),
                        on_progress=_on_progress,
                    )

                    # Store results
                    report_id = f"{selected_group}_{int(time.time())}"
                    new_report = {
                        'id': report_id,
                        'group_id': selected_group,
                        'group_name': selected_group_data['name'],
                        'overall_report': result.get('overall_report', {}),
                        'individual_reports': result.get('individual_reports', []),
                        'report_type': report_type,
                        'time_range': time_range,
                        'custom_query': custom_query,
                        'created_at': time.time()
                    }

                    # Save to session state (for immediate access)
                    if "stored_reports" not in st.session_state:
                        st.session_state.stored_reports = {}
                    st.session_state.stored_reports[report_id] = new_report
                    
                    # ⭐ Save to persistent storage
                    if backend_available and save_to_history:
                        try:
                            # Determine group type based on selected group
                            group_type_mapping = {
                                "recommend_research_group": "recommend_research_group",
                                "demo_research_group": "msra_former_interns",  # MSRA former interns
                                "StartTrack": "starttrack_group"  # 正确的组ID映射
                            }
                            group_type = group_type_mapping.get(selected_group, "recommend_research_group")
                            
                            title = f"{selected_group_data['name']}_{report_type}_{time_range}"
                            saved_path = save_achievement_report(new_report, title, group_type)
                            st.success(f"✅ Report saved to: {saved_path}")
                        except Exception as e:
                            st.warning(f"⚠️ Report generated successfully but failed to save to disk: {e}")
                    
                    st.session_state.current_view_report = new_report
                    st.session_state.current_page = "view_single_report"
                    st.session_state.page_changed = True
                    status_text.text("✅ Report generation complete!")
                    progress_bar.progress(100)
                    st.rerun()
                            
                except Exception as e:
                    st.error(f"Error during report generation: {e}")
                    progress_bar.empty()
                    status_text.empty()

def render_view_reports_page():
    """Render the view reports page with persistent storage support"""

    # Back button
    if st.button("← Back to Groups", key="back_to_groups_view", type="secondary"):
        st.session_state.current_page = "research_groups"
        st.session_state.page_changed = True
        st.rerun()
    
    # Load reports from persistent storage (all groups)
    persistent_reports = []
    if backend_available:
        try:
            persistent_reports = load_achievement_reports("all")  # Load from all groups
        except Exception as e:
            st.warning(f"⚠️ Failed to load reports from disk: {e}")
    
    # Get session stored reports (for backward compatibility)
    session_reports = st.session_state.get("stored_reports", {})
    
    # Combine persistent and session reports (convert to consistent format)
    all_reports = {}
    
    # Add persistent reports
    for report in persistent_reports:
        report_id = report.get('data', {}).get('id', f"persistent_{report.get('filename', '')}")
        all_reports[report_id] = {
            **report.get('data', {}),
            'is_persistent': True,
            'filepath': report.get('filepath', ''),
            'created_at_str': report.get('created_at', ''),
            'group_type': report.get('group_type', 'unknown'),
            'storage_category': report.get('group_type', 'unknown'),
        }
    
    # Add session reports (if not already in persistent storage)
    for report_id, report_data in session_reports.items():
        if report_id not in all_reports:
            all_reports[report_id] = {
                **report_data,
                'is_persistent': False,
            }
    
    stored_reports = all_reports

    if not stored_reports:
        st.info("🔍 No reports available. Generate some reports first using the 'Generate Report' button on group cards.")
        if st.button("Go to Groups", key="goto_groups_view_reports"):
            st.session_state.current_page = "research_groups"
            st.session_state.page_changed = True
            st.rerun()
        return

    # Statistics and filters
    st.markdown("### 📈 Report Statistics")

    # Group-based statistics
    group_stats = {
        "recommend_research_group": 0,
        "msra_former_interns": 0, 
        "starttrack_group": 0,
        "session": 0
    }
    
    for report in stored_reports.values():
        group_type = report.get('group_type', 'session')
        if group_type in group_stats:
            group_stats[group_type] += 1
        else:
            group_stats['session'] += 1

    stats_col1, stats_col2, stats_col3, stats_col4 = st.columns(4)

    with stats_col1:
        st.metric("Total Reports", len(stored_reports))

    with stats_col2:
        st.metric("Recommend Group", group_stats["recommend_research_group"])

    with stats_col3:
        st.metric("MSRA Interns", group_stats["msra_former_interns"])

    with stats_col4:
        st.metric("StartTrack Group", group_stats["starttrack_group"])
    
    # Additional row for session reports and latest report
    if group_stats["session"] > 0:
        st.markdown("**Legacy Session Reports:** " + str(group_stats["session"]))
    
    if stored_reports:
        latest_report = max(stored_reports.values(), key=lambda x: x.get('created_at', 0))
        latest_time = time.strftime('%Y-%m-%d', time.localtime(latest_report.get('created_at', time.time())))
        st.markdown(f"**Latest Report:** {latest_time}")

    # # Search and filter options
    # st.markdown("---")
    # st.markdown("### 🔍 Search & Filter")

    # filter_col1, filter_col2 = st.columns(2)

    # with filter_col1:
    #     search_term = st.text_input(
    #         "Search reports:",
    #         placeholder="Enter group name...",
    #         key="report_search",
    #         help="Search for reports by group name"
    #     )

    # with filter_col2:
    #     sort_options = ["Newest first", "Oldest first", "Group name A-Z", "Group name Z-A"]
    #     sort_by = st.selectbox("Sort by:", sort_options, key="report_sort")

    # Apply search and sorting (defaults if UI is hidden)
    filtered_reports = stored_reports.values()
    search_term = st.session_state.get("report_search", "")
    sort_by = st.session_state.get("report_sort", "Newest first")

    if search_term:
        filtered_reports = [
            report for report in filtered_reports
            if search_term.lower() in report['group_name'].lower()
        ]

    # Apply sorting
    if sort_by == "Newest first":
        sorted_reports = sorted(filtered_reports, key=lambda x: x.get('created_at', 0), reverse=True)
    elif sort_by == "Oldest first":
        sorted_reports = sorted(filtered_reports, key=lambda x: x.get('created_at', 0))
    elif sort_by == "Group name A-Z":
        sorted_reports = sorted(filtered_reports, key=lambda x: x['group_name'].lower())
    elif sort_by == "Group name Z-A":
        sorted_reports = sorted(filtered_reports, key=lambda x: x['group_name'].lower(), reverse=True)

    # Display results
    st.markdown("---")
    if search_term or sort_by != "Newest first":
        st.markdown(f"#### 📊 Available Reports ({len(sorted_reports)} found)")
    else:
        st.markdown("#### 📊 Available Reports")

    if not sorted_reports:
        st.info("🔍 No reports match your search criteria. Try adjusting your filters.")

    for report in sorted_reports:
        # Enhanced report card with more information
        created_time = time.localtime(report.get('created_at', time.time()))
        time_ago = time.time() - report.get('created_at', time.time())

        # Calculate time ago
        if time_ago < 3600:  # Less than 1 hour
            time_ago_text = f"{int(time_ago // 60)} minutes ago"
        elif time_ago < 86400:  # Less than 1 day
            time_ago_text = f"{int(time_ago // 3600)} hours ago"
        elif time_ago < 604800:  # Less than 1 week
            time_ago_text = f"{int(time_ago // 86400)} days ago"
        else:
            time_ago_text = time.strftime('%Y-%m-%d', created_time)

        # Get report type icon
        report_type_icons = {
            "Full report": "📊",
            "Recent achievements": "🏆",
            "Publication stats": "📚",
            "Collaboration network": "🤝",
            "Demo Report": "🎯"
        }
        type_icon = report_type_icons.get(report['report_type'], "📋")

        report_id = report['id']
        created_time = time.strftime('%Y-%m-%d %H:%M', created_time)
        
        card_html = textwrap.dedent(f"""
<div style="
    background: linear-gradient(135deg, #667eea15 0%, #764ba205 100%);
    border: 2px solid #667eea;
    border-radius: 15px;
    padding: 1.5rem;
    margin: 1rem 0;
    box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    transition: all 0.3s ease;
">
    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 1rem;">
        <div style="flex: 1;">
            <h4 style="margin: 0 0 0.5rem 0; color: #667eea; font-size: 1.4rem; font-weight: 600;">
                {report['group_name']}
            </h4>
            <div style="display: flex; gap: 1rem; align-items: center; flex-wrap: wrap;">
                <span style="
                    background: #4facfe;
                    color: white;
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: bold;
                ">
                    👥 {len(report.get('members', [])) if 'members' in report else len(report.get('individual_reports', []))} members
                </span>
                <span style="
                    background: #28a745;
                    color: white;
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: 500;
                ">
                    📁 {report.get('group_type', 'session').replace('_', ' ').title()}
                </span>
                <span style="
                    background: #4facfe;
                    color: white;
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: 500;
                ">
                    {type_icon} {report['report_type']}
                </span>
                <span style="
                    background: #4facfe;
                    color: white;
                    padding: 0.3rem 0.8rem;
                    border-radius: 20px;
                    font-size: 0.8rem;
                    font-weight: 500;
                ">
                    ⏰ {report['time_range']}
                </span>
            </div>
        </div>
    </div>
<div style="display: flex; justify-content: space-between; align-items: center; margin-top: 1rem; padding: 0.75rem 1rem; border-top: 1px solid #DAE8F7; background-color: #f9fafb; border-radius: 6px;">
    <div style="color: #555; font-size: 0.9rem;">
        <strong style="color:#333;">Created:</strong> {created_time} <span style="color:#888; font-size:0.9rem;">({time_ago_text})</span>
    </div>
    <div style="color: #666; font-size: 0.9rem;">
        <strong style="color:#333;">Report ID:</strong> {report_id}
    </div>
</div>

        """)
        st.markdown(card_html, unsafe_allow_html=True)

        # Action buttons for each report
        col_view, col_delete = st.columns(2)

        with col_view:
            if st.button("👁️ View Report", key=f"view_{report['id']}", use_container_width=True):
                # Set current report for viewing
                st.session_state.current_view_report = report
                st.session_state.current_page = "view_single_report"
                st.session_state.page_changed = True
                st.rerun()

        with col_delete:
            confirm_key = f"del_confirm_{report['id']}"
            if not st.session_state.get(confirm_key, False):
                if st.button("🗑️ Delete", key=f"delete_{report['id']}", use_container_width=True):
                    st.session_state[confirm_key] = True
                    st.rerun()
            else:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ Yes, Delete", key=f"confirm_yes_{report['id']}", use_container_width=True, type="primary"):
                        try:
                            # Delete from session state
                            if report['id'] in st.session_state.get("stored_reports", {}):
                                del st.session_state.stored_reports[report['id']]
                            
                            # Delete from persistent storage if applicable
                            if report.get('is_persistent', False) and report.get('filepath'):
                                if backend_available:
                                    delete_success = delete_report(report['filepath'])
                                    if delete_success:
                                        st.success(f"✅ Report '{report['group_name']}' deleted from disk.")
                                    else:
                                        st.warning(f"⚠️ Report removed from session but failed to delete from disk.")
                                        
                        except Exception as e:
                            st.error(f"❌ Error deleting report: {e}")
                        
                        st.session_state.pop(confirm_key, None)
                        st.rerun()
                with c2:
                    if st.button("❌ Cancel", key=f"confirm_no_{report['id']}", use_container_width=True, type="secondary"):
                        st.session_state.pop(confirm_key, None)
                        st.rerun()

def render_view_single_report_page():
    """Render the single report view page with detailed overall and individual reports"""

    # Back button
    if st.button("← Back to Reports", key="back_to_reports_single", type="secondary"):
        st.session_state.current_page = "view_reports"
        st.session_state.page_changed = True
        st.rerun()

    # Get the current report to view
    report_data = st.session_state.get("current_view_report")

    if not report_data:
        st.error("No report selected.")
        if st.button("Go to Reports", key="goto_reports_single"):
            st.session_state.current_page = "view_reports"
            st.session_state.page_changed = True
            st.rerun()
        return

    # Check if this is a detailed report with overall data
    is_detailed_report = "overall_report" in report_data and "individual_reports" in report_data

    if is_detailed_report:
        tab_overall, tab_cards = st.tabs(["📊 Overall Report", "👥 Individual Reports"])
        with tab_cards:
            render_member_cards_like_search(report_data["individual_reports"])
        with tab_overall:
            render_overall_report(report_data["overall_report"], report_data.get("individual_reports", []))
    else:
        # Fallback for older format
        render_group_summary(report_data)

    # # Export options
    # st.markdown("---")
    # st.markdown("### 📤 Export Options")

    # col_export1, col_export2 = st.columns(2)

    # with col_export1:
    #     if st.button("📊 Export as CSV", key="export_csv_single", type="secondary", use_container_width=True):
    #         # Convert to DataFrame for CSV export
    #         df_data = []
    #         if is_detailed_report:
    #             for member_report in report_data["individual_reports"]:
    #                 df_data.append({
    #                     'Name': member_report['name'],
    #                     'Title': member_report['header'].get('title', ''),
    #                     'Homepage': member_report['header'].get('homepage', ''),
    #                     'Email': member_report['header'].get('email', ''),
    #                     'Keywords': ', '.join(member_report.get('keywords', []))
    #                 })
    #         else:
    #             for member_report in report_data['members']:
    #                 df_data.append({
    #                     'Name': member_report['name'],
    #                     'Affiliation': member_report.get('affiliation', ''),
    #                     'Homepage': member_report.get('homepage', ''),
    #                     'Report Type': report_data.get('report_type', ''),
    #                     'Time Range': report_data.get('time_range', '')
    #                 })

    #         df = pd.DataFrame(df_data)
    #         csv = df.to_csv(index=False)
    #         st.download_button(
    #             label="💾 Download CSV",
    #             data=csv,
    #             file_name=f"{report_data.get('group_name', 'report')}_achievement_report.csv",
    #             mime="text/csv",
    #             use_container_width=True
    #         )

    # with col_export2:
    #     if st.button("📋 Export as JSON", key="export_json_single", type="secondary", use_container_width=True):
    #         json_data = json.dumps(report_data, indent=2, ensure_ascii=False)
    #         st.download_button(
    #             label="💾 Download JSON",
    #             data=json_data,
    #             file_name=f"{report_data.get('group_name', 'report')}_achievement_report.json",
    #             mime="application/json",
    #             use_container_width=True
    #         )


def render_overall_report(overall_data, individual_reports):
    """Render overall report with left navigation and People Snapshot-like UI."""
    nav_col, content_col = st.columns([0.23, 0.77])

    with nav_col:
        st.markdown("<div style='font-weight:700;color:#64748b;margin-bottom:.4rem'>Nav Bar</div>", unsafe_allow_html=True)
        # Styled button navigation similar to navigation.py
        options = ["People Snapshot", "Executive Summary", "Publications", "Service & Impact", "Research Map"]
        if "overall_nav" not in st.session_state:
            st.session_state.overall_nav = options[0]
        active = st.session_state.overall_nav
        for opt in options:
            if st.button(opt, use_container_width=True, type=("primary" if opt == active else "secondary"), key=f"overall_nav_{opt}"):
                st.session_state.overall_nav = opt
                st.rerun()
        nav = st.session_state.overall_nav

    with content_col:
        if nav == "People Snapshot":
            _render_people_snapshot(overall_data, individual_reports)
        elif nav == "Executive Summary":
            st.markdown("### Executive Summary")
            st.markdown("#### Key Milestones in the Past 24 Months")
            for x in overall_data["executive_summary"]["key_milestones"]:
                st.markdown(f"- {x}")
            st.markdown("#### Core research lines and differentiated strengths")
            for x in overall_data["executive_summary"]["core_research_lines"]:
                st.markdown(f"- {x}")
            st.markdown("#### Opportunities and needs for the next 6-12 months")
            for x in overall_data["executive_summary"]["opportunities_needs"]:
                st.markdown(f"- {x}")
        elif nav == "Publications":
            st.markdown("### Publications")
            st.markdown("#### Volume and Structure")
            for x in overall_data["publications"]["volume_structure"]:
                st.markdown(f"- {x}")
            st.markdown("#### Top-Tier Acceptance Statistics")
            for x in overall_data["publications"]["top_tier_stats"]:
                st.markdown(f"- {x}")
            st.markdown("#### Representative Works in the Past 24 Months")
            for x in overall_data["publications"]["representative_works"]:
                st.markdown(f"- {x}")
        elif nav == "Service & Impact":
            st.markdown("### Service & Impact")
            st.markdown("#### Reviewing/Program Committee/Organization")
            for x in overall_data["service_impact"]["reviewing_pc"]:
                st.markdown(f"- {x}")
            st.markdown("#### Invited Talks/Courses/Teaching")
            for x in overall_data["service_impact"]["invited_talks"]:
                st.markdown(f"- {x}")
            st.markdown("#### Media Coverage & Public Outreach / Open Source")
            for x in overall_data["service_impact"]["media_coverage"]:
                st.markdown(f"- {x}")
            for x in overall_data["service_impact"]["open_source"]:
                st.markdown(f"- {x}")
        elif nav == "Research Map":
            st.markdown("### Research Map")
            for topic in overall_data["research_map"]:
                st.markdown(f"#### {topic['topic']}")
                st.markdown(f"**Members:** {', '.join(topic['members'])}")
                st.markdown("**Representative works:**")
                for w in topic["representative_works"]:
                    st.markdown(f"- {w}")


def _render_people_snapshot(overall_data, individual_reports):
    ps = overall_data.get("people_snapshot", {})
    clusters = ps.get("research_topic_clusters", [])
    insts = ps.get("collaborators_institutions", [])
    size = ps.get("size", len(individual_reports))

    st.markdown("### People Snapshot")
    st.markdown("<div style='font-weight:700;margin:.2rem 0 .3rem 0'>Research Clusters</div>", unsafe_allow_html=True)
    chip_html = "".join([f"<span style=\"display:inline-block;padding:.25rem .6rem;border-radius:9999px;background:#e5edff;border:1px solid #c7d2fe;color:#1e3a8a;font-weight:700;margin:.2rem .35rem .2rem 0\">{_html.escape(c)}</span>" for c in clusters])
    st.markdown(f"<div>{chip_html}</div>", unsafe_allow_html=True)

    initials = [" ".join([p.strip()[:1] for p in m.get("name"," ").split()])[:2].upper() for m in individual_reports]
    st.markdown(f"<div style='opacity:.8;margin:.4rem 0'>Scale: {size} members</div>", unsafe_allow_html=True)
    bubble = "".join([f"<span style=\"display:inline-block;width:30px;height:30px;border-radius:9999px;background:#e2e8f0;color:#1f2937;display:inline-flex;align-items:center;justify-content:center;margin-right:.35rem;font-weight:700\">{_html.escape(x)}</span>" for x in initials])
    st.markdown(f"<div style='margin-bottom:.6rem'>{bubble}</div>", unsafe_allow_html=True)

    st.markdown("<div style='font-weight:700;margin:.6rem 0 .3rem 0'>Representative Collaborators/Institutions</div>", unsafe_allow_html=True)
    inst_html = "".join([f"<span style=\"display:inline-block;padding:.2rem .5rem;border-radius:9999px;border:1px solid #cbd5e1;background:#f8fafc;margin:.2rem .3rem .2rem 0\">{_html.escape(x)}</span>" for x in insts])
    st.markdown(f"<div>{inst_html}</div>", unsafe_allow_html=True)

    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    # Render all candidates in rows of 3, wrapping as needed
    for start in range(0, len(individual_reports), 3):
        row = individual_reports[start:start+3]
        cols = st.columns(3)
        for i, member in enumerate(row):
            with cols[i]:
                st.markdown(
                    f"""
                    <div style=\"background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:16px;text-align:center;box-shadow:0 10px 18px rgba(0,0,0,.06);height:350px;display:flex;flex-direction:column;justify-content:center\">\n<div style=\"font-weight:800;font-size:18px;margin:.2rem 0\">{_html.escape(member.get('name',''))}</div>\n<div style=\"opacity:.8;overflow:hidden;text-overflow:ellipsis\">{_html.escape(member.get('header',{}).get('title',''))}</div>\n</div>
                    """,
                    unsafe_allow_html=True,
                )


def render_individual_reports_detailed(individual_reports):
    """Render detailed individual member reports"""

    # Quick navigation
    member_names = [f"#{i+1} {member['name']}" for i, member in enumerate(individual_reports)]
    selected_member = st.selectbox(
        "Quick jump to member:",
        ["Select a member..."] + member_names,
        key="member_navigator_detailed",
        help="Quickly navigate to a specific member's report"
    )

    for i, member in enumerate(individual_reports, 1):
        with st.expander(f"#{i} {member['name']}", expanded=True):

            # Header
            header = member["header"]
            st.markdown(f"### {member['name']} | {header.get('title', '')}")
            if header.get('email'):
                st.markdown(f"**Email:** {header['email']}")
            if header.get('homepage'):
                st.markdown(f"**Homepage:** [{header['homepage']}]({header['homepage']})")
            if header.get('scholar'):
                st.markdown(f"**Google Scholar:** [{header['scholar']}](https://scholar.google.com)")

            # Research keywords
            st.markdown("### Research keywords")
            keywords = member.get("keywords", [])
            if keywords:
                st.markdown(" - ".join(keywords))

            # Highlights
            st.markdown("### 3-5 Highlights")
            for highlight in member.get("highlights", []):
                st.markdown(f"- {highlight}")

            # Publication overview
            st.markdown("### Publication overview")
            st.markdown(f"**Total count:** {member.get('publication_overview', 'N/A')}")
            st.markdown("**Top-tier hits in the last 24 months:** Listed in highlights above")

            # Honors/Grants
            if member.get("honors_grants"):
                st.markdown("### Honors/Grants")
                for honor in member["honors_grants"]:
                    st.markdown(f"- {honor}")

            # Academic service / invited talks
            if member.get("service_talks"):
                st.markdown("### Academic service / invited talks")
                for service in member["service_talks"]:
                    st.markdown(f"- {service}")

            # Open-source / datasets / projects
            if member.get("open_source_projects"):
                st.markdown("### Open-source / datasets / projects")
                for project in member["open_source_projects"]:
                    st.markdown(f"- {project}")

            # Representative papers
            if member.get("representative_papers"):
                st.markdown("### Representative papers")
                for paper in member["representative_papers"]:
                    st.markdown(f"- **{paper['title']}** | {paper['venue']} | {paper['year']} | {paper['links']}")


def render_member_cards_like_search(individual_reports):
    """Render members using the targeted_search candidate card UI."""
    # Theme
    current_theme = st.context.theme.type or "light"
    text_color = "#f1f5f9" if current_theme == "dark" else "#495057"

    for i, member in enumerate(individual_reports, 1):
        with st.expander(f"#{i} {member['name']}", expanded=True):
            header = member.get("header", {})
            name = member.get("name", "Unknown")
            role = header.get("title", "N/A")
            research_focus = member.get("keywords", [])
            profiles = {}
            if header.get("homepage"):
                profiles["Homepage"] = header.get("homepage")
            if header.get("scholar"):
                profiles["Google Scholar"] = header.get("scholar")

            total_score = member.get("total_score")
            radar = member.get("radar", {}) or {}

            left_col, middle_col, right_col = st.columns([1.2, 1.5, 1.3])

            with left_col:
                st.markdown(f"### {name}")
                st.markdown(f"**📍 Role:** {role}")

                if isinstance(total_score, (int, float)) and total_score > 0:
                    score_percentage = (float(total_score) / 35.0) * 100.0
                    score_color = "#10b981" if score_percentage >= 80 else ("#f59e0b" if score_percentage >= 60 else "#ef4444")
                    st.markdown(
                        f"""
                    <div style=\"background: {'#065f46' if current_theme == 'dark' else '#d1fae5'};border: 2px solid {score_color};border-radius: 12px;padding: 1rem;text-align: center;margin: 1rem 0;\">\n<div style=\"font-size: 0.9rem; color: {text_color}; margin-bottom: 0.3rem;\">Final Score</div>\n<div style=\"font-size: 2rem; font-weight: bold; color: {score_color};\">{int(total_score)}/35</div>\n<div style=\"font-size: 0.8rem; color: {text_color}; margin-top: 0.3rem;\">({score_percentage:.1f}%)</div>\n</div>
                    """,
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f"""
                    <div style=\"background: {'#374151' if current_theme == 'dark' else '#f3f4f6'};border: 2px solid {'#6b7280' if current_theme == 'dark' else '#d1d5db'};border-radius: 12px;padding: 1rem;text-align: center;margin: 1rem 0;\">\n<div style=\"font-size: 0.9rem; color: {text_color};\">Final Score</div>\n<div style=\"font-size: 2rem; font-weight: bold; color: {'#9ca3af' if current_theme == 'dark' else '#6b7280'};\">N/A</div>\n</div>
                    """,
                        unsafe_allow_html=True,
                    )

            with middle_col:
                if isinstance(radar, dict) and len(radar) > 0:
                    categories = list(radar.keys())
                    values = [radar[k] for k in categories]
                    categories_closed = categories + [categories[0]]
                    values_closed = values + [values[0]]
                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatterpolar(
                            r=values_closed,
                            theta=categories_closed,
                            fill="toself",
                            name="Profile",
                            line=dict(color="#667eea", width=2),
                            fillcolor="rgba(102, 126, 234, 0.2)",
                        )
                    )
                    fig.update_layout(
                        font=dict(size=13),
                        margin=dict(l=70, r=70, t=40, b=55),
                        polar=dict(
                            domain=dict(x=[0.08, 0.92], y=[0.1, 0.98]),
                            radialaxis=dict(visible=True, range=[0, 5]),
                            bgcolor="rgba(0,0,0,0)",
                        ),
                        showlegend=False,
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(0,0,0,0)",
                    )
                    st.plotly_chart(fig, use_container_width=False, key=f"radar_card_{i}")
                else:
                    st.markdown(
                        """
                    <div style="
                        height: 300px;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background: rgba(0,0,0,0.05);
                        border-radius: 10px;
                        color: #6b7280;
                        font-style: italic;
                    ">
                        No radar data available
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

            with right_col:
                # Inline versions of targeted_search chips/links to avoid heavy imports
                render_focus_and_profiles(research_focus, profiles, current_theme, text_color)

                if st.button(
                    "🧑 View Full Profile",
                    key=f"view_profile_member_{i}",
                    use_container_width=True,
                    type="primary",
                ):
                    reps_src = member.get("representative_papers", []) or []
                    normalized_reps = []
                    for rp in reps_src:
                        normalized_reps.append({
                            "title": rp.get("title", ""),
                            "venue": rp.get("venue", ""),
                            "year": rp.get("year", ""),
                            "type": rp.get("type", ""),
                            "links": rp.get("links", ""),
                        })

                    profile_payload = {
                        "name": name,
                        "email": header.get("email", ""),
                        "current_role_affiliation": role,
                        "current_status": "",
                        "research_keywords": research_focus,
                        "research_focus": research_focus,
                        "profiles": profiles,
                        "publication_overview": [],
                        "top_tier_hits": [],
                        "honors_grants": member.get("honors_grants", []),
                        "service_talks": member.get("service_talks", []),
                        "open_source_projects": member.get("open_source_projects", []),
                        "representative_papers": normalized_reps,
                        "highlights": member.get("highlights", []),
                        "radar": radar,
                        "total_score": total_score or 0,
                        "detailed_scores": member.get("detailed_scores", {}),
                    }
                    st.session_state["demo_candidate_overview_json"] = json.dumps(profile_payload)
                    st.session_state["prev_page"] = st.session_state.get("current_page", "📊 Achievement Report")
                    st.session_state.current_page = "🧑 Candidate Profile"
                    st.session_state.page_changed = True
                    st.rerun()


def render_focus_and_profiles(research_focus: list, profiles: dict, current_theme: str, text_color: str):
    # Chips
    if research_focus:
        if current_theme == "dark":
            chip_bg = "rgba(59,130,246,.15)"; chip_bd = "rgba(59,130,246,.35)"; chip_fg = "#e5e7eb"
        else:
            chip_bg = "#eef2ff"; chip_bd = "#c7d2fe"; chip_fg = "#0f172a"
        chip_items = []
        for x in research_focus:
            chip_items.append(
                f"<span style=\"display:inline-block;padding:.2rem .6rem;border-radius:9999px;background:{chip_bg};border:1px solid {chip_bd};color:{chip_fg};font-size:.8rem;font-weight:600;margin:.15rem .25rem .15rem 0\">{_html.escape(str(x))}</span>"
            )
        chips_html = "".join(chip_items)
        st.markdown(f"<div style='margin:.2rem 0 .5rem 0'>{chips_html}</div>", unsafe_allow_html=True)

    # Links
    items = [(k, (profiles or {}).get(k, "").strip()) for k in ["Homepage", "Google Scholar", "GitHub", "LinkedIn"] if (profiles or {}).get(k)]
    if items:
        if current_theme == "dark":
            link_color = "#93c5fd"; link_hover = "#bfdbfe"
        else:
            link_color = "#2563eb"; link_hover = "#1d4ed8"
        links_html = "".join([f'<li><a href="{u}" target="_blank" style="color:{link_color};text-decoration:none;padding:.2rem .3rem;border-radius:6px;display:inline-flex;gap:.3rem">{p}</a></li>' for p, u in items])
        st.markdown(f"<ul style='display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:.3rem .5rem;margin:.2rem 0 .4rem 0;padding:0;list-style:none'>{links_html}</ul>", unsafe_allow_html=True)


def render_group_summary(report_data):
    """Fallback rendering for older report format"""
    st.markdown("# 📊 Group Achievement Report")
    st.markdown(f"**Group:** {report_data.get('group_name', 'N/A')}")
    st.markdown(f"**Report Type:** {report_data.get('report_type', 'N/A')}")
    st.markdown(f"**Time Range:** {report_data.get('time_range', 'N/A')}")

    # Handle both old and new formats for member count
    if 'members' in report_data:
        member_count = len(report_data['members'])
    elif 'individual_reports' in report_data:
        member_count = len(report_data['individual_reports'])
    else:
        member_count = 0

    st.markdown(f"**Members:** {member_count}")


def render_individual_reports_legacy(members):
    """Fallback rendering for older member format"""
    for i, member in enumerate(members, 1):
        with st.expander(f"#{i} {member['name']}", expanded=True):
            st.markdown(f"### {member['name']}")
            if member.get('affiliation'):
                st.markdown(f"**Affiliation:** {member['affiliation']}")
            if member.get('homepage'):
                st.markdown(f"[🔗 Homepage]({member['homepage']})")
            st.markdown(member.get('report', 'No report available'))

def render_achievement_report_page():
    """Main function to render the achievement report page with navigation"""

    # Initialize current page if not set
    if "current_page" not in st.session_state:
        st.session_state.current_page = "research_groups"



    # Clear any stale state when entering the page
    if "temp_members" in st.session_state and st.session_state.current_page != "edit_group":
        del st.session_state.temp_members

    # Check if page was changed and clear any cached state
    if st.session_state.get('page_changed', False):
        st.session_state.page_changed = False
        # Force a clean state for the new page
        if "temp_members" in st.session_state and st.session_state.current_page != "edit_group":
            del st.session_state.temp_members

    # Get current page and use exact matching
    current_page = st.session_state.get('current_page', '')
    
    # Use exact string matching for pages
    if current_page == "research_groups":
        target_page = "research_groups"
    elif current_page == "edit_group":
        target_page = "edit_group"
    elif current_page == "generate_report":
        target_page = "generate_report"
    elif current_page == "view_reports":
        target_page = "view_reports"
    elif current_page == "view_single_report":
        target_page = "view_single_report"
    else:
        # For main navigation pages, map them to sub-pages
        if current_page == "📊 Achievement Report":
            target_page = "research_groups"
            st.session_state.current_page = "research_groups"
        else:
            # Fallback: reset to research groups page
            st.session_state.current_page = "research_groups"
            target_page = "research_groups"

    # Navigation logic with proper state management
    if target_page == "research_groups":
        render_research_groups_page()
    elif target_page == "edit_group":
        render_edit_group_page()
    elif target_page == "generate_report":
        render_generate_report_page()
    elif target_page == "view_reports":
        render_view_reports_page()
    elif target_page == "view_single_report":
        render_view_single_report_page()
    else:
        # Fallback: reset to research groups page
        st.session_state.current_page = "research_groups"
        render_research_groups_page()

def apply_achievement_report_styles():
    """Apply custom CSS for achievement report page"""
    # Temporarily disabled all custom styles to test button visibility
    pass
