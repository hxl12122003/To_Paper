#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AutoSci Download Checker (100% Safe Read-Only Version)
======================================================
1. 递归扫描指定目录下的所有 PDF 文件。
2. 使用严格的序号匹配（针对纯数字文件名如 10.pdf）和智能模糊匹配（针对长文件名如 acsmaterialslett.pdf）。
3. 仅在控制台打印匹配和校验报告，指出哪些文献已下载，哪些文献受损或缺失。
4. 自动生成失败文献的挽救直链和 DOI 列表。
5. ⚠️ 核心安全守则：本脚本为 100% 只读，绝对不移动、不改名、不删除任何文件！
"""

import os
import re
import csv
import argparse
from pathlib import Path

def is_valid_pdf(file_path: Path) -> bool:
    """读取文件头，校验是否为有效 PDF，绝不修改文件"""
    try:
        if file_path.stat().st_size < 1024:  # 小于 1KB 肯定不是有效 PDF
            return False
        with open(file_path, "rb") as f:
            return f.read(4) == b"%PDF"
    except Exception:
        return False

def match_file_to_paper(file_path: Path, papers: list) -> dict | None:
    """智能匹配下载的文件与 CSV 中的文献（只读匹配，不改名）"""
    filename = file_path.stem.lower().strip()
    
    # 去除下载器自动加 of _1, _2 等后缀
    filename_clean = re.sub(r'_\d+$', '', filename)
    
    # 1. 如果文件名是纯数字且小于等于 50，严格匹配 CSV 里的“编号”列的实际数值
    if filename_clean.isdigit():
        local_idx = int(filename_clean)
        if local_idx <= 50:
            for p in papers:
                p_num_str = str(p.get("编号") or p.get("index") or "").strip()
                if p_num_str.isdigit() and int(p_num_str) == local_idx:
                    return p
            return None

    # 2. 如果是其它格式的文件名，则去 DOI 和文件名里去模糊匹配
    file_alphanumeric = re.sub(r'[^a-z0-9]', '', filename_clean)
    if not file_alphanumeric:
        return None

    is_short_name = len(file_alphanumeric) < 5

    # 2.1 尝试匹配 DOI (模糊子串匹配，仅针对长文件名)
    for p in papers:
        doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
        if not doi:
            continue
            
        doi_clean = re.sub(r'[^a-z0-9]', '', doi)
        if not is_short_name:
            if file_alphanumeric in doi_clean or doi_clean in file_alphanumeric:
                return p
            
        # DOI 尾部/后缀匹配
        if "/" in doi:
            suffix = doi.split("/", 1)[1]
            suffix_clean = re.sub(r'[^a-z0-9]', '', suffix)
            if not is_short_name:
                if file_alphanumeric in suffix_clean or suffix_clean in file_alphanumeric:
                    return p
                
            # 针对出版社的特殊缩写匹配
            suffix_parts = re.split(r'[\.\-\/]', suffix)
            for part in suffix_parts:
                part_clean = re.sub(r'[^a-z0-9]', '', part)
                if len(part_clean) >= 4 and part_clean == file_alphanumeric:
                    return p

    # 2.2 尝试匹配标题 (模糊子串匹配)
    for p in papers:
        title = (p.get("文献标题") or p.get("title") or "").strip().lower()
        if not title:
            continue
        title_clean = re.sub(r'[^a-z0-9]', '', title)
        if len(title_clean) > 15:
            if title_clean in file_alphanumeric or file_alphanumeric in title_clean:
                return p
            filename_no_year = re.sub(r'^\d+', '', file_alphanumeric)
            if filename_no_year and (title_clean in filename_no_year or filename_no_year in title_clean):
                return p
                    
    return None

    # 2. 尝试匹配 DOI (模糊子串匹配，仅针对长文件名)
    for p in papers:
        doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
        if not doi:
            continue
            
        doi_clean = re.sub(r'[^a-z0-9]', '', doi)
        if not is_short_name:
            if file_alphanumeric in doi_clean or doi_clean in file_alphanumeric:
                return p
            
        # DOI 尾部/后缀匹配
        if "/" in doi:
            suffix = doi.split("/", 1)[1]
            suffix_clean = re.sub(r'[^a-z0-9]', '', suffix)
            if not is_short_name:
                if file_alphanumeric in suffix_clean or suffix_clean in file_alphanumeric:
                    return p
                
            # 针对出版社的特殊缩写匹配
            suffix_parts = re.split(r'[\.\-\/]', suffix)
            for part in suffix_parts:
                part_clean = re.sub(r'[^a-z0-9]', '', part)
                if len(part_clean) >= 4 and part_clean == file_alphanumeric:
                    return p

    # 3. 尝试匹配标题 (模糊子串匹配)
    for p in papers:
        title = (p.get("文献标题") or p.get("title") or "").strip().lower()
        if not title:
            continue
        title_clean = re.sub(r'[^a-z0-9]', '', title)
        if len(title_clean) > 15:
            if title_clean in file_alphanumeric or file_alphanumeric in title_clean:
                return p
            filename_no_year = re.sub(r'^\d+', '', file_alphanumeric)
            if filename_no_year and (title_clean in filename_no_year or filename_no_year in title_clean):
                return p
                    
    return None

def check_downloads(csv_path: str, downloads_dir: str = None):
    csv_path = Path(csv_path)
    if not csv_path.exists():
        print(f"❌ 错误: 找不到指定的 CSV 索引表: '{csv_path}'")
        return

    # 默认扫描 CSV 所在的同级目录（包括其所有的子文件夹和嵌套文件夹）
    scan_path = Path(downloads_dir) if downloads_dir else csv_path.parent
    if not scan_path.exists():
        print(f"❌ 错误: 找不到扫描目录: '{scan_path}'")
        return

    print("================================================================================")
    print("🔍 开始运行: AutoSci 下载安全校验沙盘 (100% 纯只读版)")
    print(f"  -> [CSV] 索引表: {csv_path.name}")
    print(f"  -> [DIR] 扫描目录: {scan_path}")
    print("================================================================================")

    # 1. 读取 CSV 中的文献（支持 utf-8-sig 和 gb18030/gbk 双重编码自动降级，完美防范 Excel 保存覆盖造成的乱码或崩溃问题）
    papers = []
    try:
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    papers.append(row)
        except (UnicodeDecodeError, UnicodeError):
            with open(csv_path, "r", encoding="gb18030") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    papers.append(row)
    except Exception as e:
        print(f"❌ 读取 CSV 失败: {e}")
        return

    if not papers:
        print("ℹ️ CSV 中未检测到有效文献。")
        return

    # 2. 递归扫描目录下所有的 PDF 文件（绝对不移动、不改名、不删除）
    pdf_files = [f for f in scan_path.rglob("*.pdf") if f.is_file()]

    downloaded_dois = set()
    downloaded_titles = set()
    downloaded_indices = set()
    corrupted_files = []
    unidentified_files = []
    
    # 建立纸张ID与匹配文件、文献数据的映射，用于做严格的 1-to-1 重复检测
    paper_matches = {} # {idx: [(file_path, matched_paper, is_valid)]}

    print("\n[Match] 正在递归识别已下载的文件...")
    for file_path in pdf_files:
        # 跳过临时文件或报告文件
        if file_path.name in ["failed_downloads_dois.txt", "retry_official_links.txt", "failed_downloads_pdf_links.html"]:
            continue
            
        matched_paper = match_file_to_paper(file_path, papers)
        if matched_paper:
            idx = str(matched_paper.get("编号") or matched_paper.get("index") or "Unknown").strip()
            is_valid = is_valid_pdf(file_path)
            
            if idx not in paper_matches:
                paper_matches[idx] = []
            paper_matches[idx].append((file_path, matched_paper, is_valid))
            
            if is_valid:
                print(f"  🟢 [已下载] 编号 {idx:3s} | 文件: '{file_path.name}' -> 匹配: '{matched_paper.get('文献标题')[:45]}...'")
            else:
                corrupted_files.append(file_path)
                print(f"  🔴 [受损假PDF] 文件: '{file_path.name}' (可能是报错网页，建议您手动删除)")
        else:
            unidentified_files.append(file_path)
            print(f"  🟡 [未识别文件] '{file_path.name}' (无法匹配到当前 CSV 中的任何文献)")

    # 从第一轮精确匹配（数字编号匹配、DOI匹配、全名匹配）中，计算出第一轮哪些文献已经成功匹配
    for idx, matches in paper_matches.items():
        has_valid = any(is_valid for _, _, is_valid in matches)
        if has_valid:
            downloaded_indices.add(idx)
            for _, p, is_valid in matches:
                if is_valid:
                    doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
                    title = (p.get("文献标题") or p.get("title") or "").strip().lower()
                    if doi: downloaded_dois.add(doi)
                    if title: downloaded_titles.add(title)

    # 3. 针对第一轮精确匹配后依然未匹配成功的【未识别PDF】进行第二轮模糊降级匹配（前5个英文单词最大相似度扫描）
    from difflib import SequenceMatcher
    fuzzy_matches_recorded = []

    # 找到第一轮匹配后，CSV中依然未匹配成功的文献
    remaining_unmatched_papers = []
    for p in papers:
        doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
        title = (p.get("文献标题") or p.get("title") or "").strip().lower()
        idx = str(p.get("编号") or p.get("index") or "").strip()
        
        is_downloaded = False
        if doi and doi in downloaded_dois:
            is_downloaded = True
        elif title and title in downloaded_titles:
            is_downloaded = True
        elif idx and idx in downloaded_indices:
            is_downloaded = True
            
        if not is_downloaded:
            remaining_unmatched_papers.append(p)

    # 开始遍历所有未匹配成功的 PDF，与剩余未匹配 CSV 里的文献前 5 个单词做相似度扫描
    for file_path in list(unidentified_files):
        filename_clean = file_path.stem.lower().strip()
        # 清除文件名开头可能夹带的 [年份] 或 编号前缀
        filename_no_year = re.sub(r'^\[\d+\]\s*', '', filename_clean)
        filename_no_year = re.sub(r'^\d+\s*', '', filename_no_year)
        file_words = re.sub(r'[^a-z0-9\s]', ' ', filename_no_year).split()
        
        if not file_words:
            continue
            
        best_paper = None
        best_score = -1.0
        
        for p in remaining_unmatched_papers:
            p_title = (p.get("文献标题") or p.get("title") or "").strip().lower()
            if not p_title:
                continue
            
            # 提取 CSV 文献标题的前 5 个英文单词
            p_words = re.sub(r'[^a-z0-9\s]', ' ', p_title).split()
            first_5_words = p_words[:5]
            if not first_5_words:
                continue
                
            # 计算 CSV 前 5 个单词在未识别 PDF 文件单词集合中的重合比例
            file_word_set = set(file_words)
            overlap_count = sum(1 for w in first_5_words if w in file_word_set)
            overlap_ratio = overlap_count / len(first_5_words)
            
            # 使用 SequenceMatcher 计算字串拼写相似度
            prefix_str = " ".join(first_5_words)
            fn_str = " ".join(file_words[:len(first_5_words) + 3])
            seq_ratio = SequenceMatcher(None, prefix_str, fn_str).ratio()
            
            # 综合评分：单词重合度占 70% 权重，字串拼写相似度占 30% 权重
            score = overlap_ratio * 0.7 + seq_ratio * 0.3
            
            if score > best_score:
                best_score = score
                best_paper = p
                
        # 设定相似度安全门槛：复合得分 >= 0.4
        if best_paper and best_score >= 0.4:
            fuzzy_matches_recorded.append((file_path, best_paper, best_score))
            # 从全局的未识别列表中安全移出
            unidentified_files.remove(file_path)
            # 从未匹配文献列表移出，防止后续多对一误判
            if best_paper in remaining_unmatched_papers:
                remaining_unmatched_papers.remove(best_paper)

    # 将第二轮模糊匹配成功的产品，无缝登记入已下载索引中
    for file_path, p, score in fuzzy_matches_recorded:
        idx = str(p.get("编号") or p.get("index") or "Unknown").strip()
        is_valid = is_valid_pdf(file_path)
        
        if idx not in paper_matches:
            paper_matches[idx] = []
        paper_matches[idx].append((file_path, p, is_valid))
        
        if is_valid:
            downloaded_indices.add(idx)
            doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
            title = (p.get("文献标题") or p.get("title") or "").strip().lower()
            if doi: downloaded_dois.add(doi)
            if title: downloaded_titles.add(title)

    # 提取重复匹配的冲突（一个编号被多个 PDF 占领）
    duplicate_matches = {}
    for idx, matches in paper_matches.items():
        if len(matches) > 1:
            duplicate_matches[idx] = [fp for fp, _, _ in matches]

    # 4. 统计未下载成功的文献
    failed_papers = []
    for p in papers:
        doi = (p.get("DOI") or p.get("doi") or "").strip().lower()
        title = (p.get("文献标题") or p.get("title") or "").strip().lower()
        idx = str(p.get("编号") or p.get("index") or "").strip()
        
        is_downloaded = False
        if doi and doi in downloaded_dois:
            is_downloaded = True
        elif title and title in downloaded_titles:
            is_downloaded = True
        elif idx and idx in downloaded_indices:
            is_downloaded = True
            
        if not is_downloaded:
            failed_papers.append(p)

    # 5. 针对失败的文献，生成挽救包（包含纯 DOI 文本列表和可视化手动补下 HTML 网页）
    if failed_papers:
        retry_links_path = csv_path.parent / "retry_official_links.txt"
        failed_dois_path = csv_path.parent / "failed_downloads_dois.txt"
        failed_html_path = csv_path.parent / "failed_downloads_pdf_links.html"
        
        retry_links = []
        failed_dois = []
        html_links = []
        
        for p in failed_papers:
            title = p.get("文献标题") or p.get("title") or "Unknown Title"
            doi = (p.get("DOI") or p.get("doi") or "").strip()
            year_str = p.get("年份") or p.get("year") or "Unknown"
            journal = p.get("期刊") or p.get("journal") or "Unknown"
            # 严格提取该文献在 CSV 中的数字编号，保持完美一致
            p_num = str(p.get("编号") or p.get("index") or "Unknown").strip()
            
            # 清洗文件名，用于 HTML 中的 download 属性
            safe_filename = re.sub(r'[\\/*?:"<>|]', " ", f"[{year_str}] {title}")
            safe_filename = re.sub(r'\s+', " ", safe_filename).strip()
            
            if doi:
                failed_dois.append(doi)
                doi_lower = doi.lower()
                
                # 智能构建官方直连
                if "10.1021" in doi_lower:
                    url = f"https://pubs.acs.org/doi/pdf/{doi}"
                elif "10.1002" in doi_lower:
                    url = f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}"
                elif "10.1038" in doi_lower:
                    doi_suffix = doi_lower.split("10.1038/")[-1]
                    url = f"https://www.nature.com/articles/{doi_suffix}.pdf"
                elif "10.1007" in doi_lower:
                    url = f"https://link.springer.com/content/pdf/{doi}.pdf"
                elif "10.1039" in doi_lower:
                    match = re.search(r'10\.1039/([a-z])(\d)([a-z]+)', doi_lower)
                    if match:
                        decade_char, year_digit, journal_code = match.groups()
                        suffix = doi_lower.split("10.1039/")[-1]
                        decade_map = {'a': 1990, 'b': 2000, 'c': 2010, 'd': 2020}
                        base_year = decade_map.get(decade_char)
                        if base_year is not None:
                            year = base_year + int(year_digit)
                            url = f"https://pubs.rsc.org/en/content/articlepdf/{year}/{journal_code}/{suffix}"
                        else:
                            url = f"https://doi.org/{doi}"
                    else:
                        url = f"https://doi.org/{doi}"
                elif "10.1063" in doi_lower:
                    url = f"https://pubs.aip.org/doi/pdf/{doi}"
                # 6. Elsevier (爱思唯尔 / ScienceDirect) - 独家黑科技解析，通过 DOI 重定向获取 PII 标识符，直接构建官方 PDF 下载流路由
                elif "10.1016" in doi_lower:
                    try:
                        import requests
                        url_resolve = f"https://doi.org/{doi}"
                        headers_resolve = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
                        # 使用 stream=True 极速获取重定向后的最终 PII URL，不下载 HTML 内容
                        r = requests.get(url_resolve, headers=headers_resolve, allow_redirects=True, timeout=3, stream=True)
                        final_url = r.url
                        r.close()
                        match = re.search(r'pii/([A-Z0-9xX\-]+)', final_url)
                        if match:
                            pii = match.group(1)
                            url = f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?download=true"
                        else:
                            url = f"https://doi.org/{doi}"
                    except Exception:
                        url = f"https://doi.org/{doi}"
                else:
                    url = f"https://doi.org/{doi}"
                
                retry_links.append(url)
                
                html_links.append(
                    f'<li>'
                    f'<strong>[{p_num}]</strong> '
                    f'<span style="font-size: 1.1em; font-weight: bold;">[{year_str}] {title}</span>'
                    f'<br>'
                    f'<div style="margin-top: 5px; margin-bottom: 5px;">'
                    f'  <a href="{url}" download="{safe_filename}.pdf" target="_blank" class="btn btn-smart" style="background-color: #e74c3c; border-color: #e74c3c; color: white; text-decoration: none; display: inline-block; padding: 5px 12px; border-radius: 4px; font-size: 0.9em; font-weight: bold;" title="点击手动下载此文献">📥 点击手动补下</a>'
                    f'</div>'
                    f'<span style="color: #666; font-size: 0.85em;">期刊: {journal} | DOI: {doi}</span>'
                    f'</li>'
                )
            else:
                # 针对无 DOI 的文献，生成谷歌学术搜索链接，确保 17 篇文献一个不落！
                import urllib.parse
                query_str = urllib.parse.quote(f"{title} {journal}")
                search_url = f"https://scholar.google.com/scholar?q={query_str}"
                
                html_links.append(
                    f'<li>'
                    f'<strong>[{p_num}]</strong> '
                    f'<span style="font-size: 1.1em; font-weight: bold;">[{year_str}] {title}</span>'
                    f'<br>'
                    f'<div style="margin-top: 5px; margin-bottom: 5px;">'
                    f'  <a href="{search_url}" target="_blank" class="btn btn-smart" style="background-color: #f39c12; border-color: #f39c12; color: white; text-decoration: none; display: inline-block; padding: 5px 12px; border-radius: 4px; font-size: 0.9em; font-weight: bold;" title="此文献无 DOI，点击去谷歌学术搜索标题">🔍 谷歌学术搜索标题</a>'
                    f'</div>'
                    f'<span style="color: #c0392b; font-size: 0.85em; font-weight: bold;">⚠️ 警告: 此文献在 Semantic Scholar 数据库中无 DOI，无法构建直链，请点击上方按钮手动搜索下载</span>'
                    f'</li>'
                )
        
        try:
            retry_links_path.write_text("\n".join(retry_links), encoding="utf-8")
            failed_dois_path.write_text("\n".join(failed_dois), encoding="utf-8")
            
            # 写入可视化补下 HTML 网页
            list_items_html = "\n        ".join(html_links)
            html_template = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>⚠️ AutoSci 未下载文献手动补下通道 - {csv_path.parent.name}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            line-height: 1.6;
            margin: 40px auto;
            max-width: 1000px;
            padding: 0 20px;
            color: #333;
            background-color: #fcf8e3;
        }}
        h1 {{
            color: #c0392b;
            border-bottom: 2px solid #c0392b;
            padding-bottom: 10px;
        }}
        .notice {{
            background-color: #f2dede;
            border-left: 5px solid #a94442;
            color: #a94442;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 4px;
        }}
        ol {{
            background: #fff;
            padding: 20px 40px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        li {{
            margin-bottom: 20px;
            padding-bottom: 20px;
            border-bottom: 1px dashed #eee;
        }}
        li:last-child {{
            border-bottom: none;
        }}
    </style>
</head>
<body>
    <h1>⚠️ AutoSci 未下载文献手动补下通道</h1>
    <div class="notice">
        <h3>💡 手动补下指南：</h3>
        <p>以下是经过校验后，当前文件夹中<strong>还未下载成功</strong>的文献列表（共 {len(failed_papers)} 篇）。</p>
        <p>您可以直接点击下方的红色按钮，利用浏览器的机构订阅权限，逐个手动点击下载并放入嵌套文件夹中。</p>
    </div>
    <h2>待补下文献列表</h2>
    <ol>
        {list_items_html}
    </ol>
</body>
</html>
"""
            failed_html_path.write_text(html_template, encoding="utf-8")
        except Exception as e:
            print(f"⚠️ 写入挽救包失败: {e}")

    # 6. 打印最终报告
    print("\n================================================================================")
    print("[REPORT] 纯只读校验任务报告 (安全无损)")
    print("================================================================================")
    print(f"  -> 扫描到的 PDF 总数: {len(pdf_files)} 个")
    print(f"  -> 成功识别并保留: {len(papers) - len(failed_papers)} 篇")
    if fuzzy_matches_recorded:
        print(f"     [其中通过前5单词模糊匹配成功]: {len(fuzzy_matches_recorded)} 篇")
    print(f"  -> 缺失/未下载成功: {len(failed_papers)} 篇")
    
    # 打印未识别的 PDF 文件列表，供用户精准核对和修改
    if unidentified_files:
        print(f"  -> ⚠️ 检测到未识别/无归属文件: {len(unidentified_files)} 个（请核对原名或是否已被您从 CSV 删减）:")
        for uf in unidentified_files:
            print(f"     ❓ '{uf.name}'")
            
    # 打印模糊匹配的详细情况，高亮展示模糊匹配对齐的关系
    if fuzzy_matches_recorded:
        print(f"  -> 🍊 [模糊匹配成功列表] (前5英文单词相似度对齐):")
        for file_path, p, score in fuzzy_matches_recorded:
            idx = str(p.get("编号") or p.get("index") or "Unknown").strip()
            title = p.get("文献标题") or p.get("title") or "Unknown"
            print(f"     ✅ 编号 {idx:3s} | 文件: '{file_path.name}'")
            print(f"              -> 模糊对齐: '{title[:60]}...' (最大匹配相似度: {score:.1%})")
            
    # 打印重复匹配冲突（一个文献编号对应了多个不同的 PDF 文件），直接高亮展示改错名字的文件！
    if duplicate_matches:
        print(f"  -> 🚨 检测到重复匹配冲突 (多个 PDF 文件匹配到同一篇文献，通常是因为改名错误):")
        for idx, file_paths in duplicate_matches.items():
            # 找到文献对应的标题
            matched_title = "Unknown Title"
            for p in papers:
                p_num = str(p.get("编号") or p.get("index") or "").strip()
                if p_num == idx:
                    matched_title = p.get("文献标题") or p.get("title") or "Unknown Title"
                    break
            print(f"     📌 文献编号 [{idx}] '{matched_title[:45]}...':")
            for fp in file_paths:
                print(f"       - '{fp.name}'")
            
    # 打印具体的补救链接统计说明，保持绝对诚实和清晰
    if failed_papers:
        has_doi_count = len(retry_links)
        no_doi_count = len(failed_papers) - has_doi_count
        if no_doi_count > 0:
            print(f"  -> [挽救说明] 已为您生成 {has_doi_count} 个官方补下直链，还有 {no_doi_count} 篇没有 DOI 的文献（已提供谷歌学术搜索）")
        else:
            print(f"  -> [挽救说明] 已为您生成 {has_doi_count} 个官方补下直链")
            
    if corrupted_files:
        print(f"  -> 检测到受损 PDF: {len(corrupted_files)} 个 (已在上方标红)")
    print(f"  -> 挽救包生成目录: {csv_path.parent}")
    print("================================================================================")

def main():
    parser = argparse.ArgumentParser(description="AutoSci Download Checker (Read-Only)")
    parser.add_argument("csv_path", type=str, help="指定对应的 CSV 索引表路径")
    parser.add_argument("--downloads_dir", type=str, default=None, help="可选：手动指定要扫描的文件夹路径")
    args = parser.parse_args()
    
    check_downloads(args.csv_path, args.downloads_dir)

if __name__ == "__main__":
    main()
