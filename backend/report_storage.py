"""
Report Storage System
Handles saving and loading of reports for Achievement Report and Trend Radar modules
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import streamlit as st


class ReportStorage:
    """Centralized report storage management"""
    
    def __init__(self, base_dir: str = "data"):
        self.base_dir = Path(base_dir)
        self.achievement_dir = self.base_dir / "achievement_report"
        self.trend_radar_dir = self.base_dir / "trend_radar"
        
        # Achievement Report subdirectories
        self.recommend_research_group_dir = self.achievement_dir / "recommend_research_group"
        self.msra_former_interns_dir = self.achievement_dir / "msra_former_interns"
        self.starttrack_group_dir = self.achievement_dir / "starttrack_group"
        
        # Trend Radar subdirectories
        self.domestic_dir = self.trend_radar_dir / "domestic"
        self.international_dir = self.trend_radar_dir / "international"
        
        # Ensure directories exist
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create necessary directories if they don't exist"""
        directories = [
            self.base_dir,
            self.achievement_dir,
            self.recommend_research_group_dir,
            self.msra_former_interns_dir,
            self.starttrack_group_dir,
            self.trend_radar_dir,
            self.domestic_dir,
            self.international_dir
        ]
        
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            
        # Create .gitkeep files to ensure directories are tracked
        for directory in directories:
            gitkeep_file = directory / ".gitkeep"
            if not gitkeep_file.exists():
                gitkeep_file.touch()
    
    def _generate_filename(self, report_type: str, title: str = "", extension: str = "json") -> str:
        """Generate filename with timestamp"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Clean title for filename
        if title:
            clean_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
            clean_title = clean_title.replace(' ', '_')[:50]  # Limit length
            filename = f"{report_type}_{clean_title}_{timestamp}.{extension}"
        else:
            filename = f"{report_type}_{timestamp}.{extension}"
        
        return filename
    
    def save_achievement_report(self, report_data: Dict[str, Any], title: str = "", 
                               group_type: str = "recommend_research_group") -> str:
        """Save achievement report"""
        if group_type not in ["recommend_research_group", "msra_former_interns", "starttrack_group"]:
            raise ValueError("group_type must be one of: recommend_research_group, msra_former_interns, starttrack_group")
        
        # Determine target directory based on group type
        target_dir = {
            "recommend_research_group": self.recommend_research_group_dir,
            "msra_former_interns": self.msra_former_interns_dir,
            "starttrack_group": self.starttrack_group_dir
        }[group_type]
        
        filename = self._generate_filename(f"achievement_{group_type}", title)
        filepath = target_dir / filename
        
        # Add metadata
        report_with_metadata = {
            "type": f"achievement_report_{group_type}",
            "title": title,
            "created_at": datetime.now().isoformat(),
            "filename": filename,
            "group_type": group_type,
            "data": report_data
        }
        
        # 使用临时文件确保写入的原子性，防止JSON文件损坏
        temp_filepath = filepath.with_suffix('.tmp')
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(report_with_metadata, f, ensure_ascii=False, indent=2)
            # 原子性重命名，确保文件完整性
            temp_filepath.rename(filepath)
        except Exception as e:
            # 清理临时文件
            if temp_filepath.exists():
                temp_filepath.unlink()
            raise e
        
        return str(filepath)
    
    def save_trend_radar_report(self, report_data: Dict[str, Any], title: str = "", 
                               report_type: str = "domestic") -> str:
        """Save trend radar report (domestic or international)"""
        if report_type not in ["domestic", "international"]:
            raise ValueError("report_type must be 'domestic' or 'international'")
        
        target_dir = self.domestic_dir if report_type == "domestic" else self.international_dir
        filename = self._generate_filename(f"trend_radar_{report_type}", title)
        filepath = target_dir / filename
        
        # Add metadata
        report_with_metadata = {
            "type": f"trend_radar_{report_type}",
            "title": title,
            "created_at": datetime.now().isoformat(),
            "filename": filename,
            "data": report_data
        }
        
        # 使用临时文件确保写入的原子性，防止JSON文件损坏
        temp_filepath = filepath.with_suffix('.tmp')
        try:
            with open(temp_filepath, 'w', encoding='utf-8') as f:
                json.dump(report_with_metadata, f, ensure_ascii=False, indent=2)
            # 原子性重命名，确保文件完整性
            temp_filepath.rename(filepath)
        except Exception as e:
            # 清理临时文件
            if temp_filepath.exists():
                temp_filepath.unlink()
            raise e
        
        return str(filepath)
    
    def load_achievement_reports(self, group_type: str = "all") -> List[Dict[str, Any]]:
        """Load achievement reports (all groups or specific group)"""
        reports = []
        
        if group_type == "all":
            # Load from all group directories
            search_dirs = [
                self.recommend_research_group_dir,
                self.msra_former_interns_dir,
                self.starttrack_group_dir
            ]
        elif group_type in ["recommend_research_group", "msra_former_interns", "starttrack_group"]:
            # Load from specific group directory
            target_dir = {
                "recommend_research_group": self.recommend_research_group_dir,
                "msra_former_interns": self.msra_former_interns_dir,
                "starttrack_group": self.starttrack_group_dir
            }[group_type]
            search_dirs = [target_dir]
        else:
            raise ValueError("group_type must be 'all' or one of: recommend_research_group, msra_former_interns, starttrack_group")
        
        for directory in search_dirs:
            for filepath in directory.glob("*.json"):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        report = json.load(f)
                        report["filepath"] = str(filepath)
                        reports.append(report)
                except Exception as e:
                    st.warning(f"Failed to load report {filepath.name}: {e}")
        
        # Sort by creation time (newest first)
        reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return reports
    
    def load_trend_radar_reports(self, report_type: str = "domestic") -> List[Dict[str, Any]]:
        """Load trend radar reports (domestic or international)"""
        if report_type not in ["domestic", "international"]:
            raise ValueError("report_type must be 'domestic' or 'international'")
        
        target_dir = self.domestic_dir if report_type == "domestic" else self.international_dir
        reports = []
        
        for filepath in target_dir.glob("*.json"):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    report = json.load(f)
                    report["filepath"] = str(filepath)
                    reports.append(report)
            except Exception as e:
                st.warning(f"Failed to load report {filepath.name}: {e}")
        
        # Sort by creation time (newest first)
        reports.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return reports
    
    def delete_report(self, filepath: str) -> bool:
        """Delete a report file"""
        try:
            Path(filepath).unlink()
            return True
        except Exception as e:
            st.error(f"Failed to delete report: {e}")
            return False
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """Get storage statistics"""
        stats = {
            "achievement_recommend_research": len(list(self.recommend_research_group_dir.glob("*.json"))),
            "achievement_msra_former_interns": len(list(self.msra_former_interns_dir.glob("*.json"))),
            "achievement_starttrack_group": len(list(self.starttrack_group_dir.glob("*.json"))),
            "trend_radar_domestic": len(list(self.domestic_dir.glob("*.json"))),
            "trend_radar_international": len(list(self.international_dir.glob("*.json"))),
            "total_size_mb": 0
        }
        
        # Calculate total achievement reports
        stats["achievement_reports_total"] = (
            stats["achievement_recommend_research"] + 
            stats["achievement_msra_former_interns"] + 
            stats["achievement_starttrack_group"]
        )
        
        # Calculate total size
        total_size = 0
        for directory in [
            self.recommend_research_group_dir, 
            self.msra_former_interns_dir, 
            self.starttrack_group_dir,
            self.domestic_dir, 
            self.international_dir
        ]:
            for filepath in directory.glob("*.json"):
                total_size += filepath.stat().st_size
        
        stats["total_size_mb"] = round(total_size / (1024 * 1024), 2)
        return stats


# Global storage instance
report_storage = ReportStorage()


def save_achievement_report(report_data: Dict[str, Any], title: str = "", 
                          group_type: str = "recommend_research_group") -> str:
    """Convenience function to save achievement report"""
    return report_storage.save_achievement_report(report_data, title, group_type)


def save_trend_radar_report(report_data: Dict[str, Any], title: str = "", 
                          report_type: str = "domestic") -> str:
    """Convenience function to save trend radar report"""
    return report_storage.save_trend_radar_report(report_data, title, report_type)


def load_achievement_reports(group_type: str = "all") -> List[Dict[str, Any]]:
    """Convenience function to load achievement reports"""
    return report_storage.load_achievement_reports(group_type)


def load_trend_radar_reports(report_type: str = "domestic") -> List[Dict[str, Any]]:
    """Convenience function to load trend radar reports"""
    return report_storage.load_trend_radar_reports(report_type)


def delete_report(filepath: str) -> bool:
    """Convenience function to delete a report"""
    return report_storage.delete_report(filepath)


def get_storage_stats() -> Dict[str, Any]:
    """Convenience function to get storage statistics"""
    return report_storage.get_storage_stats()
