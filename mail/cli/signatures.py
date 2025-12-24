from __future__ import annotations

def register(subparsers, *, f_export, f_sync, f_normalize):
    p_sigs = subparsers.add_parser("signatures", help="Email signatures export/sync")
    sub_sigs = p_sigs.add_subparsers(dest="signatures_cmd")

    p_sigs_export = sub_sigs.add_parser("export", help="Export signatures to YAML and files")
    p_sigs_export.add_argument("--credentials", type=str)
    p_sigs_export.add_argument("--token", type=str)
    p_sigs_export.add_argument("--out", required=True, help="Output YAML path")
    p_sigs_export.add_argument("--assets-dir", default="signatures_assets", help="Directory for exported HTML assets")
    p_sigs_export.set_defaults(func=f_export)

    p_sigs_sync = sub_sigs.add_parser("sync", help="Sync signatures from YAML")
    p_sigs_sync.add_argument("--credentials", type=str)
    p_sigs_sync.add_argument("--token", type=str)
    p_sigs_sync.add_argument("--config", required=True)
    p_sigs_sync.add_argument("--send-as", help="For Gmail: limit to this send-as email")
    p_sigs_sync.add_argument("--dry-run", action="store_true")
    p_sigs_sync.set_defaults(func=f_sync)

    p_sigs_norm = sub_sigs.add_parser("normalize", help="Render and inline a signature HTML from YAML")
    p_sigs_norm.add_argument("--config", required=True, help="Signatures YAML with default_html or gmail entries")
    p_sigs_norm.add_argument("--out-html", required=True, help="Output HTML path")
    p_sigs_norm.add_argument("--var", action="append", default=[], help="Template variable as name=value (e.g., displayName=John Doe)")
    p_sigs_norm.set_defaults(func=f_normalize)

