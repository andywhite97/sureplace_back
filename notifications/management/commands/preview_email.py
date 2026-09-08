from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.email_templates import TEMPLATES, render_email, sample_context


class Command(BaseCommand):
    help = "Render a SurePlace transactional email preview with safe sample data."

    def add_arguments(self, parser):
        parser.add_argument("template_key", choices=sorted(TEMPLATES.keys()))
        parser.add_argument("--format", choices=["html", "text"], default="html")
        parser.add_argument("--output", default="")

    def handle(self, *args, **options):
        rendered = render_email(options["template_key"], sample_context(options["template_key"]))
        content = rendered.html if options["format"] == "html" else rendered.text
        if options["output"]:
            output = Path(options["output"])
        elif options["format"] == "html":
            output = Path(settings.BASE_DIR) / "tmp" / "email-previews" / f"{options['template_key']}.html"
        else:
            self.stdout.write(content)
            return
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Rendered {rendered.template_key} preview to {output}"))
        if not output.exists():
            raise CommandError("Preview output was not created.")
