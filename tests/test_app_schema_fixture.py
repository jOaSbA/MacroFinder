"""The Android JVM tests run their SQL against a copy of the published schema.

`android/app/src/test/resources/app_schema.sql` is that copy. If it drifts
from `appdb.APP_SCHEMA`, the Kotlin queries get tested against a schema the
phone never sees. Regenerate it with:

    python -c "from bonusrank import appdb; open('android/app/src/test/resources/app_schema.sql','w',newline='\n').write(appdb.APP_SCHEMA)"
"""

from pathlib import Path

from bonusrank import appdb

FIXTURE = Path(__file__).resolve().parents[1] / "android/app/src/test/resources/app_schema.sql"


def test_the_kotlin_tests_see_the_real_schema():
    assert FIXTURE.read_text(encoding="utf-8") == appdb.APP_SCHEMA, (
        "app_schema.sql is out of date; see this file's docstring")
