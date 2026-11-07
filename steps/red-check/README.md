Proves the new checks fail before the code is written.

A pass means the checks prove nothing. A failure counts only when it is not a crash in the check's
own setup (`phoenix9/checklint.py` `broken_reason`: a Python NameError, SyntaxError, KeyError reading
os.environ, standard-library ImportError or FileNotFoundError outside /workspace raised in the check's
own code, or the shell's "unbound variable" / "command not found"). Either way the attempt fails and
the Check-writer writes the checks again.
Shell checks (`sh {files}`) run one file per container and are judged one by one.
