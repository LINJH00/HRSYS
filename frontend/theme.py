import streamlit as st


def inject_global_css():
    st.markdown(
        """
<style>
    /* Main header styling */
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        text-align: center;
        color: #1f77b4;
        margin-bottom: 2rem;
        padding: 1rem;
        background: linear-gradient(90deg, #f0f8ff, #e6f3ff);
        border-radius: 10px;
    }
    
    /* Feature cards */
    .feature-card { 
        background: white; 
        padding: 1.5rem; 
        border-radius: 10px; 
        box-shadow: 0 2px 4px rgba(0,0,0,0.1); 
        margin: 1rem 0; 
        border-left: 4px solid #1f77b4; 
    }
    
    /* Candidate cards */
    .candidate-card { 
        background: #f8f9fa; 
        padding: 1rem; 
        border-radius: 8px; 
        margin: 0.5rem 0; 
        border: 1px solid #dee2e6; 
    }
    
    /* Achievement items */
    .achievement-item { 
        background: #e8f5e8; 
        padding: 0.8rem; 
        margin: 0.5rem 0; 
        border-radius: 6px; 
        border-left: 3px solid #28a745; 
    }
    
    /* Evaluation results */
    .evaluation-result { 
        background: #fff3cd; 
        padding: 1rem; 
        border-radius: 8px; 
        border: 1px solid #ffeaa7; 
        margin: 1rem 0; 
    }
    
    /* MSRA Evaluation specific styling */
    /* FORCE BLACK TEXT FOR LIGHT THEME - HIGHEST PRIORITY */
    .msra-evaluation .msra-section-content,
    .msra-evaluation .msra-section-content li,
    .msra-evaluation .msra-section-content strong {
        color: #000000 !important;
    }
    
    .msra-evaluation {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%);
        padding: 2rem;
        border-radius: 15px;
        border: 2px solid #e1e5e9;
        margin: 1rem 0;
        box-shadow: 0 4px 20px rgba(0,0,0,0.08);
    }
    
    .msra-criteria {
        background: #f0f7ff;
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 5px solid #0066cc;
        margin: 1rem 0;
    }
    
    .msra-section {
        background: #ffffff;
        padding: 1.5rem;
        border-radius: 12px;
        margin: 1rem 0;
        border: 1px solid #e1e5e9;
        box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    }
    
    .msra-section h3 {
        color: #1e40af;
        border-bottom: 2px solid #dbeafe;
        padding-bottom: 0.5rem;
        margin-bottom: 1rem;
        font-weight: 600;
        background: #f8fafc;
        padding: 0.8rem;
        border-radius: 8px 8px 0 0;
        margin: -1.5rem -1.5rem 1rem -1.5rem;
    }
    
    .msra-section-content {
        background: #f8fafc;
        padding: 1.2rem;
        border-radius: 8px;
        border: 1px solid #e2e8f0;
        margin: 0.5rem 0;
        color: #374151;
    }
    
    .msra-section-content ul {
        margin: 0;
        padding-left: 1.5rem;
    }
    
    .msra-section-content li {
        margin: 0.5rem 0;
        color: #374151;
        line-height: 1.5;
    }
    
    .msra-section-content strong {
        color: #1e40af;
        font-weight: 600;
    }
    
    .msra-assessment {
        background: #eff6ff;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #3b82f6;
        margin: 0.5rem 0;
        color: #1e40af;
        font-weight: 500;
    }
    
    .msra-verdict {
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 12px;
        text-align: center;
        font-weight: bold;
        margin: 1rem 0;
        box-shadow: 0 4px 20px rgba(5, 150, 105, 0.25);
    }
    
    /* Dark theme support */
    @media (prefers-color-scheme: dark) {
        .msra-evaluation {
            background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
            border-color: #334155;
        }
        
        .msra-section {
            background: #1e293b;
            border-color: #334155;
            color: #f1f5f9;
        }
        
        .msra-section h3 {
            color: #38bdf8;
            border-bottom-color: #334155;
        }
        
        .msra-section-content {
            background: #0f172a;
            border-color: #334155;
            color: #f1f5f9;
        }
        
        .msra-section-content li {
            color: #f1f5f9;
        }
        
        .msra-section-content strong {
            color: #38bdf8;
        }
        
        .msra-assessment {
            background: #1e40af;
            color: #dbeafe;
        }
        
        .msra-criteria {
            background: #0c4a6e;
            border-left-color: #38bdf8;
        }
    }
    
    /* Streamlit theme detection and responsive styling */
    .msra-evaluation[data-theme="dark"],
    .msra-evaluation.theme-dark {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%) !important;
        border-color: #334155 !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-section,
    .msra-evaluation.theme-dark .msra-section {
        background: #1e293b !important;
        border-color: #334155 !important;
        color: #f1f5f9 !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-section h3,
    .msra-evaluation.theme-dark .msra-section h3 {
        color: #38bdf8 !important;
        border-bottom-color: #334155 !important;
        background: #0f172a !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-section-content,
    .msra-evaluation.theme-dark .msra-section-content {
        background: #0f172a !important;
        border-color: #334155 !important;
        color: #f1f5f9 !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-section-content li,
    .msra-evaluation.theme-dark .msra-section-content li {
        color: #f1f5f9 !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-section-content strong,
    .msra-evaluation.theme-dark .msra-section-content strong {
        color: #38bdf8 !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-assessment,
    .msra-evaluation.theme-dark .msra-assessment {
        background: #1e40af !important;
        color: #dbeafe !important;
    }
    
    .msra-evaluation[data-theme="dark"] .msra-criteria,
    .msra-evaluation.theme-dark .msra-criteria {
        background: #0c4a6e !important;
        border-left-color: #38bdf8 !important;
    }
    
    /* Light theme specific styling */
    .msra-evaluation[data-theme="light"],
    .msra-evaluation.theme-light {
        background: linear-gradient(135deg, #ffffff 0%, #f8f9fa 100%) !important;
        border-color: #e1e5e9 !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-section,
    .msra-evaluation.theme-light .msra-section {
        background: #ffffff !important;
        border-color: #e1e5e9 !important;
        color: #374151 !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-section h3,
    .msra-evaluation.theme-light .msra-section h3 {
        color: #1e40af !important;
        border-bottom-color: #dbeafe !important;
        background: #f8fafc !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-section-content,
    .msra-evaluation.theme-light .msra-section-content {
        background: #f8fafc !important;
        border-color: #e2e8f0 !important;
        color: #000000 !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-section-content li,
    .msra-evaluation.theme-light .msra-section-content li {
        color: #000000 !important;
    }
    
    /* Force black text for light theme - highest priority */
    .msra-evaluation.theme-light .msra-section-content,
    .msra-evaluation.theme-light .msra-section-content li,
    .msra-evaluation.theme-light .msra-section-content strong,
    .msra-evaluation[data-theme="light"] .msra-section-content,
    .msra-evaluation[data-theme="light"] .msra-section-content li,
    .msra-evaluation[data-theme="light"] .msra-section-content strong {
        color: #000000 !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-section-content strong,
    .msra-evaluation.theme-light .msra-section-content strong {
        color: #1e40af !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-assessment,
    .msra-evaluation.theme-light .msra-assessment {
        background: #eff6ff !important;
        color: #1e40af !important;
    }
    
    .msra-evaluation[data-theme="light"] .msra-criteria,
    .msra-evaluation.theme-light .msra-criteria {
        background: #f0f7ff !important;
        border-left-color: #0066cc !important;
    }
    
    /* Home page specific styles */
    .home-header {
        text-align: center;
        padding: 3rem 0;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 20px;
        margin-bottom: 3rem;
    }
    
    .home-feature-card {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 8px 25px rgba(0,0,0,0.1);
        margin: 1rem 0;
        transition: all 0.3s ease;
        border: 2px solid transparent;
        position: relative;
        overflow: hidden;
    }
    
    .home-feature-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 35px rgba(0,0,0,0.15);
        border-color: #667eea;
    }
    
    .home-feature-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        height: 4px;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    }
    
    .home-feature-icon {
        font-size: 3rem;
        margin-bottom: 1rem;
        text-align: center;
        display: block;
    }
    
    .stat-box {
        text-align: center;
        padding: 1.5rem;
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        border-radius: 15px;
        margin: 0 0.5rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
        cursor: pointer;
        border: none;
        width: 100%;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        position: relative;
        overflow: hidden;
    }
    
    .stat-box::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        opacity: 0;
        transition: opacity 0.3s ease;
    }
    
    .stat-box:hover::before {
        opacity: 1;
    }
    
    .stat-box:hover {
        transform: translateY(-3px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
        background: linear-gradient(135deg, #e085e8 0%, #e04a5f 100%);
    }
    
    /* Add click indicator */
    .stat-box::after {
        content: '👆 Click to navigate';
        position: absolute;
        bottom: 0.5rem;
        left: 50%;
        transform: translateX(-50%);
        font-size: 0.7rem;
        opacity: 0;
        transition: opacity 0.3s ease;
        color: rgba(255,255,255,0.8);
        background: rgba(0,0,0,0.3);
        padding: 0.2rem 0.5rem;
        border-radius: 10px;
    }
    
    .stat-box:hover::after {
        opacity: 1;
    }
    
    /* Animation keyframes for stat boxes */
    @keyframes statBoxFloat {
        0% { transform: translateY(0px); }
        50% { transform: translateY(-5px); }
        100% { transform: translateY(0px); }
    }
    
    @keyframes statBoxGlow {
        0% { box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        50% { box-shadow: 0 4px 25px rgba(240, 147, 251, 0.3); }
        100% { box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
    }
    
    /* Apply animations to stat boxes */
    .stat-box {
        animation: statBoxFloat 3s ease-in-out infinite, statBoxGlow 4s ease-in-out infinite;
    }
    
    .stat-box:hover {
        animation: none;
        transform: translateY(-3px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
        background: linear-gradient(135deg, #e085e8 0%, #e04a5f 100%);
    }
    
    /* Navigation stat box button styling */
    button[data-testid*="nav_"] {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%) !important;
        color: white !important;
        border: none !important;
        padding: 1.5rem !important;
        border-radius: 15px !important;
        margin: 0 0.5rem !important;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        cursor: pointer !important;
        width: 100% !important;
        height: 120px !important;
        display: flex !important;
        flex-direction: column !important;
        justify-content: center !important;
        align-items: center !important;
        position: relative !important;
        overflow: hidden !important;
        font-size: 0.9rem !important;
        font-weight: 500 !important;
        text-align: center !important;
        line-height: 1.4 !important;
        white-space: pre-line !important;
        animation: statBoxFloat 3s ease-in-out infinite, statBoxGlow 4s ease-in-out infinite !important;
    }
    
    button[data-testid*="nav_"]:hover {
        animation: none !important;
        transform: translateY(-3px) !important;
        box-shadow: 0 8px 25px rgba(0,0,0,0.2) !important;
        background: linear-gradient(135deg, #e085e8 0%, #e04a5f 100%) !important;
    }
    
    button[data-testid*="nav_"]:active {
        transform: translateY(-1px) !important;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3) !important;
        transition: all 0.1s ease !important;
    }
    
    button[data-testid*="nav_"]:focus {
        outline: none !important;
        box-shadow: 0 0 0 3px rgba(240, 147, 251, 0.3) !important;
    }
    
    /* Add glow effect to navigation buttons */
    button[data-testid*="nav_"]::before {
        content: '';
        position: absolute;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        opacity: 0;
        transition: opacity 0.3s ease;
    }
    
    button[data-testid*="nav_"]:hover::before {
        opacity: 1;
    }
    
    /* Enhanced button styling for navigation */
    .stButton > button {
        border-radius: 12px !important;
        font-weight: 500 !important;
        transition: all 0.3s ease !important;
        border: none !important;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
    }
    
    .stButton > button:hover {
        transform: translateY(-2px) !important;
        box-shadow: 0 6px 20px rgba(0,0,0,0.2) !important;
    }
    
    /* Primary button styling */
    .stButton > button[data-testid="baseButton-primary"] {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%) !important;
        color: white !important;
    }
    
    /* Secondary button styling */
    .stButton > button[data-testid="baseButton-secondary"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
    }
    
    /* Sidebar specific button enhancements */
    .sidebar .stButton > button {
        margin: 0.25rem 0 !important;
        padding: 0.75rem 1rem !important;
        font-size: 0.9rem !important;
    }
    
    /* Targeted Search Enhanced Styling */
    .targeted-search-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 15px;
        color: white;
        text-align: center;
        margin-bottom: 2rem;
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
    }
    
    .search-parameter-card {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin-bottom: 1rem;
        border: 2px solid #e1e5e9;
        transition: all 0.3s ease;
    }
    
    .search-parameter-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        border-color: #667eea;
    }
    
    .results-card {
        background: white;
        padding: 2rem;
        border-radius: 15px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        margin-bottom: 1rem;
        border: 2px solid #e1e5e9;
        min-height: 500px;
    }
    
    .candidate-result-card {
        background: #f8f9fa;
        border: 2px solid #e9ecef;
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        transition: all 0.3s ease;
        position: relative;
    }
    
    .candidate-result-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
        border-color: #667eea;
    }
    
    .research-focus-tag {
        background: #e3f2fd;
        color: #1976d2;
        padding: 0.2rem 0.5rem;
        border-radius: 15px;
        font-size: 0.8rem;
        margin-right: 0.5rem;
        display: inline-block;
        margin-bottom: 0.3rem;
        transition: all 0.3s ease;
    }
    
    .research-focus-tag:hover {
        background: #1976d2;
        color: white;
        transform: scale(1.05);
    }
    
    .profile-link {
        color: #667eea;
        text-decoration: none;
        margin-right: 1rem;
        transition: all 0.3s ease;
        padding: 0.2rem 0.5rem;
        border-radius: 5px;
    }
    
    .profile-link:hover {
        color: white;
        background: #667eea;
        text-decoration: none;
    }
    
    .candidate-rank-badge {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: bold;
        position: absolute;
        top: 1rem;
        right: 1rem;
    }
    
    .results-summary-banner {
        background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
        color: white;
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 1.5rem;
        text-align: center;
        font-weight: bold;
    }
    
    .empty-state {
        text-align: center;
        padding: 3rem 2rem;
        color: #6c757d;
    }
    
    .empty-state-icon {
        font-size: 4rem;
        margin-bottom: 1rem;
    }
    
    .demo-tip {
        margin-top: 2rem;
        padding: 1rem;
        background: #e3f2fd;
        border-radius: 10px;
        border-left: 4px solid #2196f3;
    }
    
    /* Dark theme support for targeted search */
    @media (prefers-color-scheme: dark) {
        .targeted-search-header {
            background: linear-gradient(135deg, #4a5568 0%, #2d3748 100%);
        }
        
        .search-parameter-card,
        .results-card {
            background: #2d3748;
            border-color: #4a5568;
            color: #e2e8f0;
        }
        
        .candidate-result-card {
            background: #2d3748;
            border-color: #4a5568;
            color: #e2e8f0;
        }
        
        .research-focus-tag {
            background: #2b6cb0;
            color: #bee3f8;
        }
        
        .research-focus-tag:hover {
            background: #bee3f8;
            color: #2b6cb0;
        }
        
        .profile-link {
            color: #90cdf4;
        }
        
        .profile-link:hover {
            color: white;
            background: #4299e1;
        }
        
        .empty-state {
            color: #a0aec0;
        }
        
        .demo-tip {
            background: #2b6cb0;
            border-left-color: #90cdf4;
            color: #bee3f8;
        }
    }
    
    /* Enhanced animations for targeted search */
    @keyframes slideInUp {
        from {
            opacity: 0;
            transform: translateY(30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    @keyframes fadeInScale {
        from {
            opacity: 0;
            transform: scale(0.95);
        }
        to {
            opacity: 1;
            transform: scale(1);
        }
    }
    
    .candidate-result-card {
        animation: slideInUp 0.5s ease-out;
    }
    
    .search-parameter-card,
    .results-card {
        animation: fadeInScale 0.6s ease-out;
    }
    
    /* Progress bar styling */
    .stProgress > div > div > div {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    }
    
    /* Metric styling */
    .metric-container {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        padding: 1rem;
        border-radius: 12px;
        text-align: center;
        margin: 0.5rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        transition: all 0.3s ease;
    }
    
    .metric-container:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 25px rgba(0,0,0,0.2);
    }
</style>
        """,
        unsafe_allow_html=True,
    )


def header():
    st.markdown('<div class="main-header">🎯 TalentScope</div>', unsafe_allow_html=True)


