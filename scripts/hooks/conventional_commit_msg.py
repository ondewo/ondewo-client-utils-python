"""
Validate a commit message with ``conventional-pre-commit``, accepting a leading ``[<TICKET>] ``.

``giticket`` prepends ``[<TICKET>] `` on ticket branches, and upstream ``conventional-pre-commit``
rejects any subject that does not START with a type. So a message that already carries the prefix
-- ``git commit --amend`` of a giticket-prefixed commit, or a hand-written prefix -- was refused,
and the only way through was ``--no-verify``, which skips every other hook as well.

This wrapper strips ONE leading ``[<TICKET>] `` from the first line and hands the rest to the
upstream hook unchanged (same arguments, same types allow-list, same output), so the validation
rules stay upstream's and only the prefix is tolerated. Wired in ``.pre-commit-config.yaml``.
"""

import re
import sys
import tempfile
from typing import (
    Final,
    List,
    Optional,
    Pattern,
)

#: The bracketed ticket giticket writes, in the same ticket shape as its ``--regex``.
TICKET_PREFIX: Final[Pattern[str]] = re.compile(r"\A\[[A-Z]{3}[0-9]{3}-[0-9]{1,5}\] ")


def strip_ticket_prefix(commit_message: str) -> str:
    """
    Remove one leading ``[<TICKET>] `` from the start of the message, if present.

    Args:
        commit_message (str):
            The raw content of the commit message file.

    Returns:
        str:
            The message without the prefix, or unchanged when it carries none.
    """
    return TICKET_PREFIX.sub("", commit_message, count=1)


def main(argv: Optional[List[str]] = None) -> int:
    """
    Run upstream ``conventional-pre-commit`` on the message with its ticket prefix removed.

    Args:
        argv (Optional[List[str]]):
            The hook arguments: the upstream options and types, then the message file path last.

    Returns:
        int:
            The upstream hook's result (0 when the message is valid).
    """
    from conventional_pre_commit import hook  # the hook's own environment, see the pre-commit config

    arguments: List[str] = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        return int(hook.main(arguments))
    *options, message_path = arguments
    with open(message_path, encoding="utf-8") as message_file:
        commit_message: str = message_file.read()
    stripped: str = strip_ticket_prefix(commit_message)
    if stripped == commit_message:
        return int(hook.main(arguments))
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".COMMIT_EDITMSG") as stripped_file:
        stripped_file.write(stripped)
        stripped_file.flush()
        return int(hook.main([*options, stripped_file.name]))


if __name__ == "__main__":
    sys.exit(main())
