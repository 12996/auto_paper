# -*- coding: utf-8 -*-
"""
================================================================================
main.py
================================================================================
ArXiv 论文翻译器 - 命令行入口

【来源说明】
本模块整合了以下 gpt_academic 项目的功能：

1. 论文下载
   - 来源: gpt_academic/crazy_functions/Latex_Function.py:91-178
   - 方法: arxiv_download()

2. Latex 处理
   - 来源: gpt_academic/crazy_functions/latex_fns/latex_actions.py
   - 方法: Latex精细分解与转化(), 编译Latex()

3. 多线程翻译
   - 来源: gpt_academic/crazy_functions/crazy_utils.py:187-350
   - 方法: request_gpt_model_multi_threads_with_very_awesome_ui_and_high_efficiency()

【使用方法】
    python main.py <arxiv_id_or_url> [options]

    示例:
        python main.py 2301.07041
        python main.py https://arxiv.org/abs/2301.07041
        python main.py 2301.07041 --no-compile
        python main.py 2301.07041 --api-base http://localhost:8080/v1

【参数说明】
    arxiv_id          ArXiv 论文 ID 或 URL（如 2301.07041）

    --api-base URL    API 基础地址（默认: http://127.0.0.1:30002/v1）
    --api-key KEY     API 密钥
    --model NAME      模型名称（默认: deepseek）
    --cache-dir DIR   缓存目录（默认: ./arxiv_cache）
    --output-dir DIR  输出目录（默认: ./output）
    --no-compile      跳过 PDF 编译
    --no-cache        不使用缓存，重新下载
    --workers N       并发线程数（默认: 5）
    --proxy URL       代理地址
    -v, --verbose     详细输出

================================================================================
"""

import os
import sys
import argparse
import time
import glob
from pathlib import Path
from typing import Optional

from loguru import logger

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

# 导入项目模块
from arxiv_translator.arxiv_downloader import ArxivDownloader
from arxiv_translator.latex_processor import (
    LatexPaperSplit,
    LatexPaperFileGroup,
    Latex精细分解与转化,
    编译Latex,
    find_main_tex_file,
    merge_tex_files,
    objdump,
)
from arxiv_translator.latex_processor.latex_toolbox import pj
from llm_client import LLMClient, translate_batch, generate_translation_prompts
from llm_client.prompts import switch_prompt

# 导入配置
import config as cfg
import shutil


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = "DEBUG" if verbose else "INFO"
    logger.remove()
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>"
    )
    # 同时输出到文件
    logger.add(
        "arxiv_translator.log",
        level="DEBUG",
        rotation="10 MB",
        encoding="utf-8"
    )


def progress_callback(index: int, total: int, status: str):
    """翻译进度回调"""
    percent = (index + 1) / total * 100
    bar_len = 40
    filled = int(bar_len * (index + 1) / total)
    bar = "=" * filled + "-" * (bar_len - filled)
    print(f"\r翻译进度: [{bar}] {percent:.1f}% ({index + 1}/{total}) - {status}", end="", flush=True)
    if index == total - 1:
        print()  # 换行


def translate_arxiv_paper(
    arxiv_input: str,
    api_base: str,
    api_key: str,
    model: str,
    cache_dir: str,
    output_dir: str,
    use_cache: bool = True,
    compile_pdf: bool = True,
    max_workers: int = 5,
    proxies: Optional[dict] = None,
    more_requirement: str = "",
    output_filename: Optional[str] = None,
) -> Path:
    """
    翻译 ArXiv 论文的完整流程

    【流程说明】
    1. 下载 ArXiv 论文 Latex 源码
    2. 解析和切分 Latex 文件
    3. 多线程调用 LLM 翻译
    4. 合并翻译结果
    5. 编译生成 PDF

    Args:
        arxiv_input: ArXiv ID 或 URL
        api_base: API 基础地址
        api_key: API 密钥
        model: 模型名称
        cache_dir: 缓存目录
        output_dir: 输出目录（None 则使用缓存目录）
        use_cache: 是否使用缓存
        compile_pdf: 是否编译 PDF
        max_workers: 并发线程数
        proxies: 代理配置
        more_requirement: 额外翻译要求
        output_filename: 自定义输出文件名（不含扩展名，None 则自动生成）

    Returns:
        输出目录路径
    """
    start_time = time.time()

    # ==================== 1. 下载论文 ====================
    logger.info("=" * 60)
    logger.info("步骤 1/5: 下载 ArXiv 论文")
    logger.info("=" * 60)

    downloader = ArxivDownloader(cache_dir=cache_dir, proxies=proxies)
    extract_path, arxiv_id = downloader.download(arxiv_input, use_cache=use_cache)

    if not arxiv_id:
        # 本地文件
        logger.info(f"使用本地文件: {extract_path}")
        arxiv_id = extract_path.name

    logger.info(f"论文 ID: {arxiv_id}")
    logger.info(f"解压路径: {extract_path}")

    # ==================== 2. 解析 Latex ====================
    logger.info("=" * 60)
    logger.info("步骤 2/5: 解析 Latex 文件")
    logger.info("=" * 60)

    # 查找所有 tex 文件
    file_manifest = [f for f in glob.glob(f'{extract_path}/**/*.tex', recursive=True)]
    if len(file_manifest) == 0:
        raise RuntimeError(f"找不到任何 .tex 文件: {extract_path}")

    logger.info(f"找到 {len(file_manifest)} 个 tex 文件")

    # 找到主文件
    maintex = find_main_tex_file(file_manifest, 'translate_zh')
    logger.info(f"主文件: {maintex}")

    # 创建工作目录
    work_folder = pj(cache_dir, arxiv_id, 'workfolder')
    os.makedirs(work_folder, exist_ok=True)

    # 复制 bbl 文件（如果有）
    main_tex_basename = os.path.basename(maintex)[:-4]  # 去掉 .tex
    may_exist_bbl = pj(extract_path, f'{main_tex_basename}.bbl')
    # 先用临时名称，后面会重命名
    if os.path.exists(may_exist_bbl):
        shutil.copyfile(may_exist_bbl, pj(work_folder, 'merge.bbl'))

    # 复制辅助文件（.sty, .bst, 图片等）到 workfolder
    # 这些文件对编译是必需的
    auxiliary_patterns = ['*.sty', '*.bst', '*.cls', '*.fd', '*.def']
    for pattern in auxiliary_patterns:
        for src_file in glob.glob(f'{extract_path}/**/{pattern}', recursive=True):
            dst_file = pj(work_folder, os.path.basename(src_file))
            if not os.path.exists(dst_file):
                shutil.copyfile(src_file, dst_file)
                logger.debug(f"复制辅助文件: {os.path.basename(src_file)}")

    # 复制图片目录（如果存在）
    # 常见的图片目录名
    img_dir_names = ['images', 'fig', 'figures', 'assets', 'img', 'pics', 'picture', 'sup_mat']

    # 先检查 tex 文件中引用的图片路径
    all_image_dirs = set()
    for tex_file in glob.glob(f'{extract_path}/**/*.tex', recursive=True):
        try:
            with open(tex_file, 'r', encoding='utf-8', errors='replace') as f:
                tex_content = f.read()
            # 查找 \includegraphics 中的路径
            import re
            matches = re.findall(r'\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}', tex_content)
            for match in matches:
                # 提取目录部分
                img_path = match.split('/')[0] if '/' in match else ''
                if img_path and not img_path.startswith('.'):
                    all_image_dirs.add(img_path)
        except:
            pass

    # 合并预定义目录和从 tex 中提取的目录
    all_img_dirs = set(img_dir_names) | all_image_dirs

    for img_dir_name in all_img_dirs:
        for src_img_dir in glob.glob(f'{extract_path}/**/{img_dir_name}', recursive=True):
            if os.path.isdir(src_img_dir):
                dst_img_dir = pj(work_folder, img_dir_name)
                if not os.path.exists(dst_img_dir):
                    shutil.copytree(src_img_dir, dst_img_dir)
                    logger.info(f"复制图片目录: {src_img_dir} -> {dst_img_dir}")
                break  # 每种目录名只复制第一个

    # 合并 tex 文件
    with open(maintex, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    merged_content = merge_tex_files(extract_path, content, 'translate_zh')

    with open(pj(work_folder, 'merge.tex'), 'w', encoding='utf-8') as f:
        f.write(merged_content)

    logger.info("Latex 文件合并完成")

    # ==================== 3. 切分 Latex ====================
    logger.info("=" * 60)
    logger.info("步骤 3/5: 切分 Latex 文件")
    logger.info("=" * 60)

    lps = LatexPaperSplit()
    lps.read_title_and_abstract(merged_content)
    logger.info(f"论文标题: {lps.title[:50]}...")

    # 生成输出文件名
    if output_filename:
        # 用户指定了文件名，直接使用
        final_output_filename = output_filename
    else:
        # 从标题自动生成文件名
        import re
        clean_title = lps.title
        clean_title = re.sub(r'\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{[^}]*\}', '', clean_title)
        clean_title = re.sub(r'\\[a-zA-Z]+\*?', '', clean_title)
        clean_title = re.sub(r'[{}$]', '', clean_title)
        clean_title = re.sub(r'\s+', '_', clean_title)
        clean_title = re.sub(r'[^\w\u4e00-\u9fff\-]', '', clean_title)
        clean_title = clean_title.strip('_-')[:50]
        if not clean_title or len(clean_title) < 3:
            clean_title = arxiv_id
        final_output_filename = clean_title
    logger.info(f"输出文件名: {final_output_filename}")

    segments = lps.split(merged_content, work_folder)
    logger.info(f"切分完成，共 {len(segments)} 个片段")

    # 按 token 分组
    pfg = LatexPaperFileGroup()
    for index, r in enumerate(segments):
        pfg.file_paths.append(f'segment-{index}')
        pfg.file_contents.append(r)
    pfg.run_file_split(max_token_limit=cfg.MAX_TOKEN_PER_FRAGMENT)

    n_split = len(pfg.sp_file_contents)
    logger.info(f"按 token 限制分组后，共 {n_split} 个翻译任务")

    # ==================== 4. 多线程翻译 ====================
    logger.info("=" * 60)
    logger.info("步骤 4/5: 调用 LLM 翻译")
    logger.info("=" * 60)

    # 初始化 LLM 客户端
    llm_client = LLMClient(
        api_base=api_base,
        api_key=api_key,
        model=model,
        temperature=cfg.TEMPERATURE,
        max_tokens=cfg.MAX_TOKENS,
        timeout=cfg.TIMEOUT,
    )

    # 生成提示词
    _switch_prompt_ = lambda pfg, mode: switch_prompt(pfg, mode, more_requirement)
    inputs_array, sys_prompt_array = _switch_prompt_(pfg, 'translate_zh')

    # 执行翻译
    logger.info(f"开始翻译，并发数: {max_workers}")
    results = translate_batch(
        texts=["" for _ in range(n_split)],  # text 已包含在 inputs_array (user_prompts) 中
        system_prompts=sys_prompt_array,
        user_prompts=inputs_array,  # inputs_array 包含完整翻译指令+原文
        llm_client=llm_client,
        max_workers=max_workers,
        callback=progress_callback,
    )

    # 重新组合结果（因为 inputs_array 包含了完整的 prompt）
    # 这里需要从翻译结果中提取纯文本
    pfg.sp_file_result = results
    pfg.merge_result()

    # ==================== 5. 合并结果 ====================
    logger.info("=" * 60)
    logger.info("步骤 5/5: 合并结果并编译 PDF")
    logger.info("=" * 60)

    # 合并翻译结果
    model_name = model.replace('_', '\\_')
    msg = f"当前大语言模型: {model_name}，当前语言模型温度设定: {cfg.TEMPERATURE}。"
    final_tex = lps.merge_result(pfg.file_result, 'translate_zh', msg)

    # 确定最终输出目录
    if output_dir:
        final_output_dir = Path(output_dir)
        final_output_dir.mkdir(parents=True, exist_ok=True)
    else:
        final_output_dir = Path(work_folder)

    # 保存结果到最终输出目录
    output_tex_path = pj(final_output_dir, f'{final_output_filename}.tex')
    with open(output_tex_path, 'w', encoding='utf-8') as f:
        f.write(final_tex)

    logger.info(f"翻译后的 tex 文件: {output_tex_path}")

    # 保存序列化结果（用于编译错误回退）
    objdump((lps, pfg.file_result, 'translate_zh', msg), file=pj(work_folder, 'merge_result.pkl'))

    # 复制 bbl 文件（用新文件名）
    if os.path.exists(pj(work_folder, 'merge.bbl')):
        shutil.copyfile(pj(work_folder, 'merge.bbl'), pj(final_output_dir, f'{final_output_filename}.bbl'))

    # 编译 PDF（仍在 work_folder 中进行，然后复制到输出目录）
    if compile_pdf:
        logger.info("开始编译 PDF...")

        # 复制 tex 文件到 work_folder 用于编译
        shutil.copyfile(output_tex_path, pj(work_folder, f'{final_output_filename}.tex'))

        success = 编译Latex(
            project_folder=work_folder,
            main_file_original='merge',
            main_file_modified=final_output_filename,
            mode='translate_zh',
            callback=lambda msg: logger.info(msg),
        )

        if success:
            # 复制生成的 PDF 到输出目录
            pdf_src = pj(work_folder, f'{final_output_filename}.pdf')
            pdf_dst = pj(final_output_dir, f'{final_output_filename}.pdf')
            if pdf_src != pdf_dst:
                shutil.copyfile(pdf_src, pdf_dst)

            # 复制双语对照 PDF
            comparison_src = pj(work_folder, 'comparison.pdf')
            if os.path.exists(comparison_src):
                comparison_dst = pj(final_output_dir, 'comparison.pdf')
                shutil.copyfile(comparison_src, comparison_dst)
                logger.info(f"双语对照 PDF: {comparison_dst}")

            logger.info(f"翻译完成! PDF 文件: {pdf_dst}")
        else:
            logger.warning("PDF 编译失败，但 tex 文件已生成")
    else:
        logger.info("跳过 PDF 编译")

    # 计算耗时
    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"翻译完成! 总耗时: {elapsed:.1f} 秒")
    logger.info(f"输出目录: {final_output_dir}")
    logger.info("=" * 60)

    return Path(final_output_dir)


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="ArXiv 论文翻译器 - 将英文论文翻译为中文",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s 2301.07041
  %(prog)s https://arxiv.org/abs/2301.07041
  %(prog)s 2301.07041 --api-base http://localhost:8080/v1 --model gpt-4
  %(prog)s 2301.07041 --no-compile  # 只生成 tex 文件
        """
    )

    parser.add_argument(
        "arxiv_id",
        help="ArXiv 论文 ID 或 URL（如 2301.07041）"
    )

    parser.add_argument(
        "--api-base",
        default=cfg.API_BASE,
        help=f"API 基础地址（默认: {cfg.API_BASE}）"
    )

    parser.add_argument(
        "--api-key",
        default=cfg.API_KEY,
        help="API 密钥"
    )

    parser.add_argument(
        "--model",
        default=cfg.MODEL_NAME,
        help=f"模型名称（默认: {cfg.MODEL_NAME}）"
    )

    parser.add_argument(
        "--cache-dir",
        default=str(cfg.CACHE_DIR),
        help=f"缓存目录（默认: {cfg.CACHE_DIR}）"
    )

    parser.add_argument(
        "--output-dir",
        default=str(cfg.OUTPUT_DIR),
        help=f"输出目录（默认: {cfg.OUTPUT_DIR}）"
    )

    parser.add_argument(
        "--no-compile",
        action="store_true",
        help="跳过 PDF 编译"
    )

    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用缓存，重新下载"
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=cfg.MAX_WORKERS,
        help=f"并发线程数（默认: {cfg.MAX_WORKERS}）"
    )

    parser.add_argument(
        "--proxy",
        help="代理地址（如 http://127.0.0.1:7890）"
    )

    parser.add_argument(
        "--requirement",
        default="",
        help="额外翻译要求（如专业词汇说明）"
    )

    parser.add_argument(
        "--output-name",
        default=None,
        help="自定义输出文件名（不含扩展名，如 'my_paper'）"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细输出"
    )

    args = parser.parse_args()

    # 配置日志
    setup_logging(args.verbose)

    # 代理配置
    proxies = None
    if args.proxy:
        proxies = {
            "http": args.proxy,
            "https": args.proxy,
        }

    try:
        output_path = translate_arxiv_paper(
            arxiv_input=args.arxiv_id,
            api_base=args.api_base,
            api_key=args.api_key,
            model=args.model,
            cache_dir=args.cache_dir,
            output_dir=args.output_dir,
            use_cache=not args.no_cache,
            compile_pdf=not args.no_compile,
            max_workers=args.workers,
            proxies=proxies,
            more_requirement=args.requirement,
            output_filename=args.output_name,
        )
        print(f"\n✓ 翻译完成! 输出目录: {output_path}")

    except KeyboardInterrupt:
        logger.warning("用户中断")
        sys.exit(1)
    except Exception as e:
        logger.error(f"翻译失败: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
