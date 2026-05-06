from django.core.management.base import BaseCommand, CommandError

from books.catalog_seed import import_catalog_seed_jsonl


class Command(BaseCommand):
    help = "Import catalog books from a JSONL seed file."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to a JSONL seed file")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and count changes without saving them",
        )

    def handle(self, *args, **options):
        path = options["path"]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        except OSError as exc:
            raise CommandError(str(exc)) from exc

        stats = import_catalog_seed_jsonl(content, dry_run=options["dry_run"])
        self.stdout.write(
            self.style.SUCCESS(
                "seen={seen} created={created} updated={updated} skipped={skipped} "
                "authors_created={authors_created} genres_created={genres_created} "
                "languages_created={languages_created} publishers_created={publishers_created} "
                "series_created={series_created}".format(**stats.__dict__)
            )
        )
        for error in stats.errors[:20]:
            self.stderr.write(error)
        if stats.errors:
            raise CommandError(f"{len(stats.errors)} import errors")
