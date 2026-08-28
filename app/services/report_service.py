"""
Report Service — generates an Excel daily report of all job activity.

Uses openpyxl to create a formatted spreadsheet with:
- Summary sheet: daily stats
- Jobs sheet: all jobs found today with scores
- Applications sheet: emails sent
"""
import logging
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.styles import (
    Alignment,
    Border,
    Font,
    PatternFill,
    Side,
)
from openpyxl.utils import get_column_letter

from app.config.settings import REPORTS_DIR

logger = logging.getLogger(__name__)


HEADER_FILL = PatternFill("solid", fgColor="1a1a2e")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
ALT_FILL = PatternFill("solid", fgColor="F0F4FF")
GREEN_FILL = PatternFill("solid", fgColor="C8F7C5")
YELLOW_FILL = PatternFill("solid", fgColor="FFF9C4")
RED_FILL = PatternFill("solid", fgColor="FFCCCC")

thin = Side(style="thin", color="CCCCCC")
thin_border = Border(left=thin, right=thin, top=thin, bottom=thin)


class ReportService:
    """
    Generates formatted Excel reports of daily job search activity.
    """

    def __init__(self):
        self.reports_dir = Path(REPORTS_DIR)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def generate_daily_report(
        self,
        scored_jobs: list[dict],
        applications: list[dict],
        run_stats: dict,
    ) -> str:
        """
        Generate a comprehensive daily Excel report.

        Args:
            scored_jobs: [{"job_id", "title", "company", "score", "reasoning", "job_url", ...}]
            applications: [{"title", "company", "to_email", "email_sent", "resume_path"}]
            run_stats: {"total_fetched", "new_jobs", "qualified", "emails_sent", ...}

        Returns:
            Path to generated Excel file
        """
        today = date.today().strftime("%Y-%m-%d")
        filename = f"JobReport_{today}.xlsx"
        filepath = self.reports_dir / filename

        wb = openpyxl.Workbook()

        # Build sheets
        self._build_summary_sheet(wb, today, run_stats, scored_jobs)
        self._build_jobs_sheet(wb, scored_jobs)
        self._build_applications_sheet(wb, applications)

        # Remove default sheet
        if "Sheet" in wb.sheetnames:
            del wb["Sheet"]

        try:
            wb.save(str(filepath))
        except PermissionError:
            from datetime import datetime as _dt
            suffix = _dt.now().strftime("%H%M%S")
            filename = f"JobReport_{today}_{suffix}.xlsx"
            filepath = self.reports_dir / filename
            wb.save(str(filepath))

        logger.info(f"📊 Excel report saved: {filepath}")
        return str(filepath)

    def _build_summary_sheet(self, wb, today: str, stats: dict, scored_jobs: list[dict]):
        ws = wb.create_sheet("📊 Summary", 0)
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 20

        # Title
        ws.merge_cells("A1:B1")
        ws["A1"] = f"🤖 AI Job Agent — Daily Report — {today}"
        ws["A1"].font = Font(bold=True, size=14, color="1a1a2e")
        ws["A1"].alignment = Alignment(horizontal="center")

        rows = [
            ("Metric", "Value"),
            ("Date", today),
            ("Total Jobs Fetched", stats.get("total_fetched", 0)),
            ("New Jobs Saved", stats.get("new_jobs", 0)),
            ("Duplicates Skipped", stats.get("duplicates_skipped", 0)),
            ("Jobs Scored (AI)", len(scored_jobs)),
            ("Qualified Jobs (≥65)", stats.get("qualified", 0)),
            ("Resumes Generated", stats.get("resumes_generated", 0)),
            ("Emails Sent", stats.get("emails_sent", 0)),
            ("WhatsApp Sent", "Yes" if stats.get("whatsapp_sent") else "No"),
        ]

        for i, (key, val) in enumerate(rows, start=3):
            ws[f"A{i}"] = key
            ws[f"B{i}"] = val
            ws[f"A{i}"].border = thin_border
            ws[f"B{i}"].border = thin_border
            if i == 3:  # Header row
                ws[f"A{i}"].fill = HEADER_FILL
                ws[f"A{i}"].font = HEADER_FONT
                ws[f"B{i}"].fill = HEADER_FILL
                ws[f"B{i}"].font = HEADER_FONT
            elif i % 2 == 0:
                ws[f"A{i}"].fill = ALT_FILL
                ws[f"B{i}"].fill = ALT_FILL

        # Top 5 matches table
        ws["A14"] = "🏆 Top 5 Matches"
        ws["A14"].font = Font(bold=True, size=12)

        top_jobs = sorted(scored_jobs, key=lambda x: x.get("score", 0), reverse=True)[:5]
        headers = ["Rank", "Title", "Company", "Score", "Action", "URL"]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=15, column=col, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.border = thin_border

        for rank, job in enumerate(top_jobs, 1):
            row = 15 + rank
            score = job.get("score", 0)
            fill = GREEN_FILL if score >= 75 else YELLOW_FILL if score >= 65 else RED_FILL
            for col, val in enumerate([
                rank,
                job.get("title", ""),
                job.get("company", ""),
                f"{score}/100",
                job.get("recommended_action", ""),
                job.get("job_url", ""),
            ], 1):
                cell = ws.cell(row=row, column=col, value=val)
                cell.border = thin_border
                if col in (1, 4):
                    cell.fill = fill

        ws.column_dimensions["B"].width = 35
        ws.column_dimensions["C"].width = 25
        ws.column_dimensions["F"].width = 50

    def _build_jobs_sheet(self, wb, scored_jobs: list[dict]):
        ws = wb.create_sheet("📋 All Jobs")

        headers = [
            "Job ID", "Title", "Company", "Score", "Recommended Action",
            "Reasoning", "Matching Skills", "Missing Skills", "URL",
        ]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.border = thin_border

        sorted_jobs = sorted(scored_jobs, key=lambda x: x.get("score", 0), reverse=True)

        for row_num, job in enumerate(sorted_jobs, start=2):
            score = job.get("score", 0)
            fill = GREEN_FILL if score >= 75 else YELLOW_FILL if score >= 65 else RED_FILL

            values = [
                job.get("job_id", ""),
                job.get("title", ""),
                job.get("company", ""),
                score,
                job.get("recommended_action", ""),
                job.get("reasoning", ""),
                ", ".join(job.get("matching_skills", [])),
                ", ".join(job.get("missing_skills", [])),
                job.get("job_url", ""),
            ]
            for col, val in enumerate(values, 1):
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.border = thin_border
                if col == 4:  # Score column gets color
                    cell.fill = fill
                elif row_num % 2 == 0:
                    cell.fill = ALT_FILL

        # Column widths
        widths = [8, 35, 25, 8, 12, 50, 35, 35, 50]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    def _build_applications_sheet(self, wb, applications: list[dict]):
        ws = wb.create_sheet("📧 Applications")

        headers = [
            "Title", "Company", "Score", "Email To",
            "Email Sent", "Resume Generated", "Date",
        ]
        for col, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=h)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.border = thin_border

        for row_num, app in enumerate(applications, start=2):
            values = [
                app.get("title", ""),
                app.get("company", ""),
                app.get("score", ""),
                app.get("to_email", "N/A"),
                "✅" if app.get("email_sent") else "❌",
                "✅" if app.get("resume_path") else "❌",
                app.get("date", date.today().strftime("%Y-%m-%d")),
            ]
            for col, val in enumerate(values, 1):
                cell = ws.cell(row=row_num, column=col, value=val)
                cell.border = thin_border
                if row_num % 2 == 0:
                    cell.fill = ALT_FILL

        widths = [35, 25, 8, 35, 12, 18, 12]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
