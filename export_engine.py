"""
export_engine.py
Document Assembly Engine using Jinja2 to render institutional UPHSD CCS Syllabi.
Generates filenames using Course Code and Course Title.
"""

import os
import re
import webbrowser
from jinja2 import Environment, FileSystemLoader, select_autoescape
from db_manager import DatabaseManager

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
EXPORTS_DIR = os.path.join(os.path.dirname(__file__), "exports")


class SyllabusExportEngine:
    def __init__(self, db_manager: DatabaseManager, templates_dir: str = TEMPLATES_DIR, exports_dir: str = EXPORTS_DIR):
        self.db_manager = db_manager
        self.templates_dir = templates_dir
        self.exports_dir = exports_dir
        os.makedirs(self.exports_dir, exist_ok=True)

        self.jinja_env = Environment(
            loader=FileSystemLoader(self.templates_dir),
            autoescape=select_autoescape(["html", "xml"])
        )

    def render_and_export(self, course_code: str, template_name: str = "uphsd_ccs_template.html", auto_open: bool = False) -> str:
        """
        Renders the syllabus from SQLite into a browser-ready HTML document.
        Exports filename format: <COURSE_CODE>_<COURSE_TITLE>.html
        """
        data = self.db_manager.get_syllabus(course_code)
        if not data:
            raise ValueError(f"No syllabus found in database for course code: {course_code}")

        template = self.jinja_env.get_template(template_name)
        rendered_html = template.render(
            metadata=data["metadata"],
            course_outcomes=data["course_outcomes"],
            weekly_schedules=data["weekly_schedules"]
        )

        # 1. Sanitize the Course Title for Windows filesystem safety (removes :, /, \, etc.)
        raw_title = data["metadata"]["course_title"]
        safe_title = re.sub(r'[\\/*?:"<>|]', '', raw_title).strip()
        title_slug = safe_title.replace(" ", "_")

        # 2. Sanitize Course Code (e.g., 'BSCS 3109 / 3109L' -> 'BSCS_3109_3109L')
        safe_code = re.sub(r'[\\/*?:"<>|]', '', course_code).strip()
        code_slug = safe_code.replace(" ", "_")

        # 3. Formulate the customized filename
        output_filename = f"{code_slug}_{title_slug}.html"
        output_filepath = os.path.join(self.exports_dir, output_filename)

        # 4. Write HTML file to disk
        with open(output_filepath, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        print(f"[EXPORT ENGINE] Successfully compiled syllabus -> {output_filepath}")

        # 5. Optionally launch in default browser
        if auto_open:
            webbrowser.open(f"file://{os.path.abspath(output_filepath)}")

        return output_filepath


if __name__ == "__main__":
    db = DatabaseManager()
    exporter = SyllabusExportEngine(db)
    
    # Test export with the first available subject
    try:
        courses = db.list_all_courses()
        if courses:
            first_course = courses[0]["course_code"]
            print(f"Testing export for {first_course}...")
            exporter.render_and_export(first_course, auto_open=True)
        else:
            print("Database has no courses yet. Run main.py first.")
    except Exception as e:
        print(f"Export demo notice: {e}")