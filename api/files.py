# -*- coding: utf-8 -*-
"""
api/files.py — 本地 PDF 文件服务

GET /api/files/<path:file_path>  提供本地 PDF 文件的 HTTP 访问
"""
from __future__ import annotations

import os
import urllib.parse
from pathlib import Path

from flask import Blueprint, send_file, jsonify, request, abort

ROOT = Path(__file__).parent.parent

files_bp = Blueprint("files", __name__, url_prefix="/api")


@files_bp.get("/files/<path:file_path>")
def serve_file(file_path: str):
    """
    服务本地文件（用于前端 iframe 加载 PDF）。

    file_path 是 URL 编码的绝对路径或相对于项目根目录的路径。
    例：GET /api/files/output%2F2301.07041%2Fcomparison.pdf
    """
    # URL 解码
    decoded = urllib.parse.unquote(file_path)

    # 如果是绝对路径，直接使用；否则拼接项目根目录
    if os.path.isabs(decoded):
        abs_path = Path(decoded)
    else:
        abs_path = ROOT / decoded

    # 安全检查：只允许访问 pdf 文件，且文件必须存在
    if not abs_path.exists():
        return jsonify({"error": f"文件不存在: {decoded}"}), 404

    if abs_path.suffix.lower() != ".pdf":
        return jsonify({"error": "只支持 PDF 文件访问"}), 403

    return send_file(
        abs_path,
        mimetype="application/pdf",
        as_attachment=False,   # inline 展示，不弹下载框
    )


@files_bp.get("/files/by-arxiv/<arxiv_id>/<file_type>")
def serve_paper_pdf(arxiv_id: str, file_type: str):
    """
    按 arxiv_id 和文件类型提供 PDF。

    file_type:
        - comparison  → comparison.pdf（双语对照，详情页使用）
        - translated  → 中文翻译 PDF
        - original    → 原始英文 PDF

    例：GET /api/files/by-arxiv/2301.07041/comparison
    """
    from db import get_db_manager
    db = get_db_manager()
    paper = db.get_paper(arxiv_id)

    if paper is None:
        return jsonify({"error": f"论文不存在: {arxiv_id}"}), 404

    path_map = {
        "comparison": paper.comparison_pdf_path,
        "translated": paper.translated_pdf_path,
        "original":   paper.original_pdf_path,
    }

    if file_type not in path_map:
        return jsonify({"error": f"未知文件类型: {file_type}，支持: comparison/translated/original"}), 400

    pdf_path = path_map[file_type]
    if not pdf_path or not os.path.exists(pdf_path):
        return jsonify({"error": f"{file_type} PDF 尚不存在，论文状态: {paper.status.value}"}), 404

    return send_file(Path(pdf_path), mimetype="application/pdf", as_attachment=False)
