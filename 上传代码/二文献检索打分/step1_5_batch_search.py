#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Step 1.5: Batch Literature Search & Last-Abstract Extractor
===========================================================
该脚本读取 D:\ARS\关键词两词加部分三词组合.txt (或 D:\ARS\关键词三三组合.txt)，
对每组关键词组合进行 Semantic Scholar API 检索。
- 两词组合：获取前 80 篇文献。
- 三词组合：获取前 20 篇文献。
从第一组开始，进行全局去重。去重后将各组的文献信息和摘要保存，
并提取各组中去重后相关度最低（最后一篇）的摘要，合并为一个文档，
供用户直接提交给 DeepSeek 评估检索饱和度（Relevance Decay）。
同时，脚本会单独统计“两词组合”和“三词组合”贡献的新文献数量，帮助评估是否需要做三词组合。
"""

import os
import sys
import json
import time
from pathlib import Path

# 确保能导入同级目录下的 search_papers
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from search_papers import SemanticScholarSearcher
except ImportError:
    print("❌ 错误: 无法导入 search_papers.py，请确保该文件在当前目录下。")
    sys.exit(1)

# 路径配置
KEYWORD_FILE_2PLUS3 = Path(r"D:\ARS\关键词两词加部分三词组合.txt")
KEYWORD_FILE_33 = Path(r"D:\ARS\关键词三三组合.txt")

OUTPUT_BASE_DIR = Path(r"D:\ARS\AutoSci-main\wiki\outputs\batch_search")
GROUPS_DIR = OUTPUT_BASE_DIR / "groups"
LAST_ABSTRACTS_DIR = OUTPUT_BASE_DIR / "last_abstracts"
 
def main():
    print("=" * 80)
    print("🚀 开始运行 Step 1.5: 双词/三词组合关键词批量检索与检索饱和度分析")
    print("=" * 80)

    # 1. 选择正确的关键词组合文件
    if KEYWORD_FILE_2PLUS3.exists():
        KEYWORD_FILE = KEYWORD_FILE_2PLUS3
        print(f"✅ 检测到最新的双词+部分三词组合文件：'{KEYWORD_FILE.name}'")
    elif KEYWORD_FILE_33.exists():
        KEYWORD_FILE = KEYWORD_FILE_33
        print(f"ℹ️ 未检测到双词文件，退回使用三三组合文件：'{KEYWORD_FILE.name}'")
    else:
        print(f"❌ 错误: 找不到任何关键词文件（尝试了 '{KEYWORD_FILE_2PLUS3.name}' 和 '{KEYWORD_FILE_33.name}'）")
        sys.exit(1)

    # 2. 初始化 Semantic Scholar 检索器
    searcher = SemanticScholarSearcher()
    
    # 3. 读取关键词组合
    lines = KEYWORD_FILE.read_text(encoding="utf-8").splitlines()
    groups = [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    print(f"✅ 成功加载了 {len(groups)} 组关键词组合。")

    # 4. 创建输出目录
    GROUPS_DIR.mkdir(parents=True, exist_ok=True)
    LAST_ABSTRACTS_DIR.mkdir(parents=True, exist_ok=True)

    # 全局去重集合与统计指标
    seen_paper_ids = set()
    total_new_papers = 0
    combined_abstracts = []

    # 详细统计，用于判断三词组合是否带来新文献
    stats = {
        "2_word": {"groups": 0, "retrieved": 0, "new_unique": 0},
        "3_word": {"groups": 0, "retrieved": 0, "new_unique": 0},
        "other": {"groups": 0, "retrieved": 0, "new_unique": 0}
    }

    # 5. 逐组进行检索与处理
    for idx, group_text in enumerate(groups, 1):
        # 解析关键词
        kws = [k.strip() for k in group_text.split(",") if k.strip()]
        num_kws = len(kws)
        
        if num_kws < 2:
            print(f"\n👉 [{idx}/{len(groups)}] ⚠️ 警告: 关键词数量不足 2 个，跳过该组: '{group_text}'")
            continue

        # 根据关键词个数，决定检索数量限制 (Limit) 和检索式
        # 按照用户最新要求：两词组合 and 三词组合全部检索 80 篇
        limit = 80
        if num_kws == 2:
            group_type = "2_word"
            query = f'"{kws[0]}" "{kws[1]}"'
            type_desc = "双词组合"
        elif num_kws == 3:
            group_type = "3_word"
            query = f'"{kws[0]}" "{kws[1]}" "{kws[2]}"'
            type_desc = "三词组合"
        else:
            group_type = "other"
            query = " ".join([f'"{k}"' for k in kws])
            type_desc = f"{num_kws}词组合"

        # 断点续传逻辑：检查该组的 JSON 结果是否已经存在且完整
        group_json_path = GROUPS_DIR / f"group_{idx:02d}_papers.json"
        has_run = False
        if group_json_path.exists():
            try:
                with open(group_json_path, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                
                # 校验缓存数据的完整性
                cached_papers = cached_data.get("papers", [])
                cached_retrieved = cached_data.get("total_retrieved", 0)
                cached_new_unique = cached_data.get("new_unique_count", 0)
                
                # 将已检索到的文献 ID 重新加载到全局去重集合中，确保去重逻辑的连续性
                for paper in cached_papers:
                    pid = paper.get("paperId")
                    if pid:
                        seen_paper_ids.add(pid)
                
                # 累加统计指标
                stats[group_type]["groups"] += 1
                stats[group_type]["retrieved"] += cached_retrieved
                stats[group_type]["new_unique"] += cached_new_unique
                total_new_papers += cached_new_unique
                
                # 重建该组的摘要文本，用于最终的合并文件
                if cached_papers:
                    last_paper = cached_papers[-1]
                    title = last_paper.get("title", "Unknown Title")
                    authors = ", ".join([a.get("name", "Unknown") for a in last_paper.get("authors", [])])
                    year = last_paper.get("year", "N/A")
                    doi = (last_paper.get("externalIds") or {}).get("DOI", "No DOI")
                    pid = last_paper.get("paperId", "No ID")
                    abstract = last_paper.get("abstract") or "No abstract available in Semantic Scholar database."
                    orig_rank = last_paper.get("original_rank", limit)
                    
                    abstract_text = (
                        f"Group ID: {idx:02d} ({type_desc})\n"
                        f"Keywords: {group_text}\n"
                        f"Paper Title: {title}\n"
                        f"Authors: {authors}\n"
                        f"Year: {year}\n"
                        f"DOI: {doi}\n"
                        f"S2 Paper ID: {pid}\n"
                        f"Original Rank: {orig_rank}/{limit}\n"
                        f"Unique Papers in this Group: {cached_new_unique}\n"
                        f"{'=' * 80}\n"
                        f"--- Abstract ---\n"
                        f"{abstract}\n"
                        f"{'=' * 80}\n\n"
                    )
                    combined_abstracts.append(abstract_text)
                else:
                    placeholder_text = (
                        f"Group ID: {idx:02d} ({type_desc})\n"
                        f"Keywords: {group_text}\n"
                        f"Status: [No new unique papers after global deduplication]\n"
                        f"{'=' * 80}\n\n"
                    )
                    combined_abstracts.append(placeholder_text)
                
                print(f"⏭️  [{idx}/{len(groups)}] [断点续传] 检测到该组已处理，已成功加载缓存并【跳过】(新增去重文献: {cached_new_unique} 篇)")
                has_run = True
            except Exception as e:
                print(f"⚠️  [{idx}/{len(groups)}] 读取缓存文件 '{group_json_path.name}' 失败 ({e})，将重新运行该组检索。")
                has_run = False

        if has_run:
            continue

        print(f"\n👉 [{idx}/{len(groups)}] 正在处理第 {idx} 组 ({type_desc}): '{group_text}'")
        print(f"  🔍 构建精准检索式: {query} | 本组限制数量: {limit} 篇")
        
        # 调用 API 检索文献
        try:
            raw_papers = searcher.search_papers(query, limit=limit)
        except Exception as e:
            print(f"  ❌ 调用 API 检索失败: {e}")
            # 记录失败状态，在合并文件中标记
            placeholder_text = (
                f"Group ID: {idx:02d} ({type_desc})\n"
                f"Keywords: {group_text}\n"
                f"Status: [API Request Failed: {e}]\n"
                f"{'=' * 80}\n\n"
            )
            combined_abstracts.append(placeholder_text)
            continue
            
        # 6. 全局去重
        unique_papers = []
        for rank, paper in enumerate(raw_papers, 1):
            pid = paper.get("paperId")
            if not pid:
                continue
            if pid not in seen_paper_ids:
                seen_paper_ids.add(pid)
                # 记录原始检索排名，方便后续追踪
                paper["original_rank"] = rank
                unique_papers.append(paper)
                
        # 更新该类型的统计指标
        stats[group_type]["groups"] += 1
        stats[group_type]["retrieved"] += len(raw_papers)
        stats[group_type]["new_unique"] += len(unique_papers)
        total_new_papers += len(unique_papers)
        
        print(f"  ➜ 检索到 {len(raw_papers)} 篇文献 | 全局去重后新增: {len(unique_papers)} 篇。")

        # 7. 保存该组的所有唯一文章信息和摘要 (JSON 格式)
        group_data = {
            "group_id": idx,
            "group_type": group_type,
            "keywords": kws,
            "query": query,
            "total_retrieved": len(raw_papers),
            "new_unique_count": len(unique_papers),
            "papers": unique_papers
        }
        
        with open(group_json_path, "w", encoding="utf-8") as f:
            json.dump(group_data, f, ensure_ascii=False, indent=2)
            
        # 8. 提取去重后的最后一篇（相关度可能最低的一篇）的摘要，单独保存并加入合并
        if unique_papers:
            # 最后一篇
            last_paper = unique_papers[-1]
            title = last_paper.get("title", "Unknown Title")
            authors = ", ".join([a.get("name", "Unknown") for a in last_paper.get("authors", [])])
            year = last_paper.get("year", "N/A")
            doi = (last_paper.get("externalIds") or {}).get("DOI", "No DOI")
            pid = last_paper.get("paperId", "No ID")
            abstract = last_paper.get("abstract") or "No abstract available in Semantic Scholar database."
            orig_rank = last_paper.get("original_rank", limit)
            
            abstract_text = (
                f"Group ID: {idx:02d} ({type_desc})\n"
                f"Keywords: {group_text}\n"
                f"Paper Title: {title}\n"
                f"Authors: {authors}\n"
                f"Year: {year}\n"
                f"DOI: {doi}\n"
                f"S2 Paper ID: {pid}\n"
                f"Original Rank: {orig_rank}/{limit}\n"
                f"Unique Papers in this Group: {len(unique_papers)}\n"
                f"{'=' * 80}\n"
                f"--- Abstract ---\n"
                f"{abstract}\n"
                f"{'=' * 80}\n\n"
            )
            
            abstract_txt_path = LAST_ABSTRACTS_DIR / f"group_{idx:02d}_last_abstract.txt"
            with open(abstract_txt_path, "w", encoding="utf-8") as f:
                f.write(abstract_text)
                
            combined_abstracts.append(abstract_text)
            print(f"  💾 最后一篇(相关度最低)摘要已单独提取存盘: group_{idx:02d}_last_abstract.txt")
        else:
            placeholder_text = (
                f"Group ID: {idx:02d} ({type_desc})\n"
                f"Keywords: {group_text}\n"
                f"Status: [No new unique papers after global deduplication]\n"
                f"{'=' * 80}\n\n"
            )
            combined_abstracts.append(placeholder_text)
            print(f"  ℹ️ 该组去重后无新增文献，不生成最后一篇摘要。")

        # 9. 按照用户要求，每完成一组检索，强制休息 60 秒（1分钟）以保护 API
        if idx < len(groups):
            print(f"  ⏳ [安全保护] 已完成第 {idx} 组。为防止 API 429 频控限制并保持长期稳定运行，强制休眠 60 秒...")
            time.sleep(60.0)

    # 10. 写入合并后的总摘要文件
    combined_file_path = OUTPUT_BASE_DIR / "all_last_abstracts_combined.txt"
    with open(combined_file_path, "w", encoding="utf-8") as f:
        f.write("# =========================================================================\n")
        f.write(f"# AutoSci 关键词检索 - 最后一篇相关度最低的摘要合并列表 (共 {len(groups)} 组)\n")
        f.write("# 可直接复制并整体发送给 DeepSeek 进行检索饱和度 (Relevance Decay) 评估！\n")
        f.write("# =========================================================================\n\n")
        f.write("".join(combined_abstracts))

    # 10. 输出极为精美的最终学术统计报告
    print("\n" + "=" * 80)
    print("✨ Step 1.5 批量文献检索与低相关度摘要提取完毕！")
    print("=" * 80)
    print(f"📊 【全局去重统计结果】")
    print(f"  ➜ 累计检索发现的完全不重复文献总数: {total_new_papers} 篇")
    
    # 计算双词统计
    t_groups = stats["2_word"]["groups"]
    t_retrieved = stats["2_word"]["retrieved"]
    t_new = stats["2_word"]["new_unique"]
    t_ratio = (t_new / total_new_papers * 100) if total_new_papers > 0 else 0
    print(f"  🟢 双词组合 (检索限额 80 篇):")
    print(f"    - 处理组数: {t_groups} 组")
    print(f"    - 检索到总文献: {t_retrieved} 篇")
    print(f"    - 去重后贡献新文献: {t_new} 篇 (占比 {t_ratio:.2f}%)")
    
    # 计算三词统计
    th_groups = stats["3_word"]["groups"]
    th_retrieved = stats["3_word"]["retrieved"]
    th_new = stats["3_word"]["new_unique"]
    th_ratio = (th_new / total_new_papers * 100) if total_new_papers > 0 else 0
    print(f"  🔵 三词组合 (检索限额 80 篇):")
    print(f"    - 处理组数: {th_groups} 组")
    print(f"    - 检索到总文献: {th_retrieved} 篇")
    print(f"    - 去重后【增量贡献】新文献: {th_new} 篇 (占比 {th_ratio:.2f}%)")
    
    # 其他组合 (如果有)
    if stats["other"]["groups"] > 0:
        o_groups = stats["other"]["groups"]
        o_retrieved = stats["other"]["retrieved"]
        o_new = stats["other"]["new_unique"]
        o_ratio = (o_new / total_new_papers * 100) if total_new_papers > 0 else 0
        print(f"  🟡 其他多词组合 (检索限额 80 篇):")
        print(f"    - 处理组数: {o_groups} 组")
        print(f"    - 检索到总文献: {o_retrieved} 篇")
        print(f"    - 去重后增量贡献新文献: {o_new} 篇 (占比 {o_ratio:.2f}%)")
        
    print("-" * 80)
    print(f"📂 组文献详情（含各组所有去重文献）已存入: {GROUPS_DIR}")
    print(f"📂 最后一篇摘要（单文件版）已存入: {LAST_ABSTRACTS_DIR}")
    print(f"📝 完美合成的总摘要文件已生成: {combined_file_path}")
    print("\n💡 【深度饱和度对比结论】")
    if th_new == 0:
        print("  ➜ ⚠️ 三词组合【没有】贡献任何新文献！说明双词组合已经完全覆盖了该领域的所有相关内容。")
    elif th_ratio < 5.0:
        print(f"  ➜ 💡 三词组合仅带来了极少的新文献 ({th_new} 篇，仅占 {th_ratio:.2f}%)。")
        print("    这说明两词检索（限额 80 篇）的饱和度极高，您后续基本无需再花费精力去跑剩下的 1600 个三词组合了！")
    else:
        print(f"  ➜ 🚀 三词组合带来了显著的增量文献 ({th_new} 篇，占比 {th_ratio:.2f}%)。")
        print("    说明对于极度精准的研究，三词精确检索式仍然能召回一些被双词泛检索所遗漏的高价值文献。")
    print("=" * 80)

if __name__ == "__main__":
    main()