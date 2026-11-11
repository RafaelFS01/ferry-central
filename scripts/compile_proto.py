"""Compila proto/telemetry.proto para stubs Python gRPC em src/proto/."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from grpc_tools import protoc


def compile_proto(proto_dir: Path, out_dir: Path) -> None:
    """Executa protoc e ajusta imports para o pacote src.proto."""
    proto_file = proto_dir / "telemetry.proto"
    if not proto_file.exists():
        raise FileNotFoundError(f"Arquivo .proto não encontrado: {proto_file}")

    out_dir.mkdir(parents=True, exist_ok=True)
    args = [
        "grpc_tools.protoc",
        f"-I{proto_dir}",
        f"--python_out={out_dir}",
        f"--pyi_out={out_dir}",
        f"--grpc_python_out={out_dir}",
        str(proto_file),
    ]
    exit_code = protoc.main(args)
    if exit_code != 0:
        raise RuntimeError(f"protoc falhou com código de saída {exit_code}.")

    grpc_file = out_dir / "telemetry_pb2_grpc.py"
    content = grpc_file.read_text(encoding="utf-8")
    patched = re.sub(
        r"^import telemetry_pb2 as telemetry__pb2$",
        "from src.proto import telemetry_pb2 as telemetry__pb2",
        content,
        flags=re.MULTILINE,
    )
    grpc_file.write_text(patched, encoding="utf-8")


if __name__ == "__main__":
    central_root = Path(__file__).resolve().parent.parent
    repo_root = central_root.parent
    proto_path = Path(sys.argv[1]) if len(sys.argv) > 1 else repo_root / "proto"
    target_path = central_root / "src" / "proto"
    compile_proto(proto_path, target_path)
    print(f"Stubs gerados com sucesso em {target_path}")

