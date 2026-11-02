"""The `phoenix doctor` command: check this installation (--quick, --for-update, or everything)."""
from phoenix9 import doctor
from phoenix9.cli.output import show
from phoenix9.ops import common, doctor as ops_doctor


def add(sub, common_parser) -> None:
    """Register doctor."""
    p = sub.add_parser("doctor", parents=[common_parser], help="check this installation")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--quick", action="store_true", help="only the cheap checks (services, API, home, secrets, disk)")
    group.add_argument("--for-update", action="store_true", dest="for_update",
                       help="the checks an update needs (no Claude session)")
    p.set_defaults(func=run)


def run(args) -> int:
    """Run the checks; exit 0 only when every one passed."""
    mode = "quick" if args.quick else "for-update" if args.for_update else "full"
    common.record_command(args.who, f"doctor{' --' + mode if mode != 'full' else ''}")
    data = ops_doctor.run(mode=mode)
    show(args, data, doctor.render(data))
    return 0 if data["ok"] else 1
