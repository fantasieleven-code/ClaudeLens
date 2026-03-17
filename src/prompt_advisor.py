#!/usr/bin/env python3
"""
Prompt Advisor - 基于真实会话数据分析具体改进机会
扫描JSONL文件，找出：
1. 高成本低效率的prompt（可精简）
2. 可用Agent并行的连续独立操作
3. 未先Read就Edit的操作
"""

import os
import json
import glob
import sqlite3
from datetime import datetime, timedelta

SESSIONS_DIR = os.path.expanduser("~/.claude/projects")
EFFICIENCY_DB = os.path.expanduser("~/.claude/efficiency.db")

# 模型定价
PRICING = {
    "claude-opus-4-6": {"input": 15.0, "output": 75.0, "cache_write": 18.75, "cache_read": 1.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30},
}
DEFAULT_P = PRICING["claude-sonnet-4-6"]


def calc_msg_cost(msg):
    """计算单条assistant消息成本"""
    usage = msg.get("message", {}).get("usage", {})
    model = msg.get("message", {}).get("model", "")
    p = DEFAULT_P
    for k, v in PRICING.items():
        if k in model:
            p = v
            break
    inp = usage.get("input_tokens", 0)
    out = usage.get("output_tokens", 0)
    cw = usage.get("cache_creation_input_tokens", 0)
    cr = usage.get("cache_read_input_tokens", 0)
    return round(inp * p["input"] / 1e6 + out * p["output"] / 1e6 + cw * p["cache_write"] / 1e6 + cr * p["cache_read"] / 1e6, 4)


def extract_text(content):
    """提取用户消息文本"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return " ".join(texts).strip()
    return ""


def extract_project(filepath):
    parts = filepath.split("/")
    for i, p in enumerate(parts):
        if p == "projects" and i + 1 < len(parts):
            proj_dir = parts[i + 1]
            if "-Projects-" in proj_dir:
                return proj_dir.split("-Projects-", 1)[1]
            if proj_dir.startswith("-Users-"):
                return "global"
            return proj_dir
    return "unknown"


def parse_session_for_advice(filepath):
    """解析单个会话，提取tool序列和用户消息"""
    project = extract_project(filepath)
    session_id = os.path.basename(filepath).replace(".jsonl", "")

    events = []  # [{type, timestamp, content/tool_name, cost, ...}]

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")
            timestamp = data.get("timestamp", "")

            if msg_type == "user":
                text = extract_text(data.get("message", {}).get("content", ""))
                if text and len(text) > 2:
                    events.append({
                        "type": "user",
                        "timestamp": timestamp,
                        "text": text,
                    })

            elif msg_type == "assistant":
                msg = data.get("message", {})
                cost = calc_msg_cost(data)
                usage = msg.get("usage", {})
                out_tokens = usage.get("output_tokens", 0)

                # 提取tool calls
                tool_calls = []
                contents = msg.get("content", [])
                if isinstance(contents, list):
                    for block in contents:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool_name = block.get("name", "")
                            tool_input = block.get("input", {})
                            # 提取关键参数
                            file_path = tool_input.get("file_path", "")
                            command = tool_input.get("command", "")[:120] if tool_input.get("command") else ""
                            tool_calls.append({
                                "tool": tool_name,
                                "file_path": file_path,
                                "command": command,
                            })

                events.append({
                    "type": "assistant",
                    "timestamp": timestamp,
                    "cost": cost,
                    "output_tokens": out_tokens,
                    "tool_calls": tool_calls,
                })

    return {
        "session_id": session_id,
        "project": project,
        "events": events,
    }


def find_edit_without_read(events):
    """找出Edit/Write前未Read目标文件的情况"""
    results = []
    recent_reads = set()  # 最近读过的文件

    for i, ev in enumerate(events):
        if ev["type"] == "user":
            # 新的用户消息，不清空recent_reads（保持在整个对话中）
            continue

        if ev["type"] == "assistant":
            for tc in ev.get("tool_calls", []):
                if tc["tool"] == "Read" and tc["file_path"]:
                    recent_reads.add(tc["file_path"])
                elif tc["tool"] in ("Edit", "Write") and tc["file_path"]:
                    if tc["file_path"] not in recent_reads:
                        # 找到对应的用户消息
                        user_msg = ""
                        for j in range(i - 1, -1, -1):
                            if events[j]["type"] == "user":
                                user_msg = events[j]["text"][:150]
                                break
                        results.append({
                            "timestamp": ev["timestamp"],
                            "file": tc["file_path"],
                            "tool": tc["tool"],
                            "user_prompt": user_msg,
                            "suggestion": f"在{tc['tool']} {os.path.basename(tc['file_path'])} 之前应先 Read 该文件，确保理解现有代码结构和上下文。",
                        })
                    # Edit/Write后也算"了解"了这个文件
                    recent_reads.add(tc["file_path"])

    return results


def find_parallel_opportunities(events):
    """找出可用Agent并行的连续独立操作"""
    results = []

    # 找连续的assistant消息中，同类独立操作
    i = 0
    while i < len(events):
        ev = events[i]
        if ev["type"] != "assistant":
            i += 1
            continue

        # 收集从当前用户指令开始的所有tool calls序列
        tool_sequence = []
        user_msg = ""
        # 找前面最近的用户消息
        for j in range(i - 1, -1, -1):
            if events[j]["type"] == "user":
                user_msg = events[j]["text"][:200]
                break

        # 收集连续assistant消息中的tool calls
        j = i
        while j < len(events) and events[j]["type"] == "assistant":
            for tc in events[j].get("tool_calls", []):
                tool_sequence.append({
                    "tool": tc["tool"],
                    "file_path": tc["file_path"],
                    "command": tc["command"],
                    "timestamp": events[j]["timestamp"],
                })
            j += 1

        # 分析是否有可并行的独立操作组
        # 模式1: 连续多个Read不同文件
        consecutive_reads = []
        for tc in tool_sequence:
            if tc["tool"] == "Read":
                consecutive_reads.append(tc)
            else:
                if len(consecutive_reads) >= 3:
                    files = [os.path.basename(r["file_path"]) for r in consecutive_reads[:5]]
                    results.append({
                        "type": "sequential_reads",
                        "timestamp": consecutive_reads[0]["timestamp"],
                        "user_prompt": user_msg,
                        "count": len(consecutive_reads),
                        "files": files,
                        "suggestion": f"连续读取了{len(consecutive_reads)}个文件（{', '.join(files[:3])}...），可以用一条prompt要求Claude并行读取，或用Agent子任务分别探索。",
                    })
                consecutive_reads = []
        # 检查末尾
        if len(consecutive_reads) >= 3:
            files = [os.path.basename(r["file_path"]) for r in consecutive_reads[:5]]
            results.append({
                "type": "sequential_reads",
                "timestamp": consecutive_reads[0]["timestamp"],
                "user_prompt": user_msg,
                "count": len(consecutive_reads),
                "files": files,
                "suggestion": f"连续读取了{len(consecutive_reads)}个文件（{', '.join(files[:3])}...），可以用一条prompt要求Claude并行读取，或用Agent子任务分别探索。",
            })

        # 模式2: 连续多个Grep/Glob搜索
        consecutive_searches = []
        for tc in tool_sequence:
            if tc["tool"] in ("Grep", "Glob"):
                consecutive_searches.append(tc)
            else:
                if len(consecutive_searches) >= 3:
                    results.append({
                        "type": "sequential_searches",
                        "timestamp": consecutive_searches[0]["timestamp"],
                        "user_prompt": user_msg,
                        "count": len(consecutive_searches),
                        "suggestion": f"连续执行了{len(consecutive_searches)}次搜索，这些搜索可能是独立的。用Agent(subagent_type='Explore')可以一次性并行完成多个代码搜索。",
                    })
                consecutive_searches = []

        # 模式3: 连续多个Bash命令
        consecutive_bash = []
        for tc in tool_sequence:
            if tc["tool"] == "Bash":
                consecutive_bash.append(tc)
            else:
                if len(consecutive_bash) >= 3:
                    cmds = [b["command"][:60] for b in consecutive_bash[:4]]
                    results.append({
                        "type": "sequential_bash",
                        "timestamp": consecutive_bash[0]["timestamp"],
                        "user_prompt": user_msg,
                        "count": len(consecutive_bash),
                        "commands": cmds,
                        "suggestion": f"连续执行了{len(consecutive_bash)}条Bash命令，如果命令之间无依赖，可以用 && 合并或要求Claude并行调用多个Bash。",
                    })
                consecutive_bash = []

        i = j

    return results


def _summarize_actions(tool_calls_list):
    """从tool_calls列表中提取实际产出摘要"""
    reads = []
    edits = []
    writes = []
    searches = []
    bashes = []
    agents = 0
    other = []

    for tc in tool_calls_list:
        tool = tc["tool"]
        fp = tc.get("file_path", "")
        fname = os.path.basename(fp) if fp else ""
        cmd = tc.get("command", "")

        if tool == "Read" and fname:
            reads.append(fname)
        elif tool == "Edit" and fname:
            edits.append(fname)
        elif tool == "Write" and fname:
            writes.append(fname)
        elif tool in ("Grep", "Glob"):
            searches.append(tool)
        elif tool == "Bash" and cmd:
            bashes.append(cmd[:60])
        elif tool == "Agent":
            agents += 1
        elif tool:
            other.append(tool)

    parts = []
    if reads:
        unique = list(dict.fromkeys(reads))[:4]
        parts.append(f"读取了 {', '.join(unique)}{'等' if len(reads) > 4 else ''}")
    if edits:
        unique = list(dict.fromkeys(edits))[:4]
        parts.append(f"修改了 {', '.join(unique)}{'等' if len(edits) > 4 else ''}")
    if writes:
        unique = list(dict.fromkeys(writes))[:3]
        parts.append(f"创建了 {', '.join(unique)}")
    if searches:
        parts.append(f"搜索了{len(searches)}次")
    if bashes:
        parts.append(f"执行了{len(bashes)}条命令")
    if agents:
        parts.append(f"启动了{agents}个Agent")

    return "；".join(parts) if parts else "仅文本回复，无工具操作"


def _generate_better_prompt(user_msg, tool_calls_list, total_cost, total_output):
    """根据实际产出生成'建议这样问'"""
    reads = [tc for tc in tool_calls_list if tc["tool"] == "Read"]
    edits = [tc for tc in tool_calls_list if tc["tool"] == "Edit"]
    writes = [tc for tc in tool_calls_list if tc["tool"] == "Write"]
    bashes = [tc for tc in tool_calls_list if tc["tool"] == "Bash"]
    searches = [tc for tc in tool_calls_list if tc["tool"] in ("Grep", "Glob")]

    edit_files = list(dict.fromkeys([os.path.basename(tc["file_path"]) for tc in edits if tc.get("file_path")]))
    write_files = list(dict.fromkeys([os.path.basename(tc["file_path"]) for tc in writes if tc.get("file_path")]))
    changed_files = edit_files + write_files

    # 无工具调用 = 纯文本回复，建议直接指令
    if not tool_calls_list:
        if total_output > 3000:
            return f"建议: 加上'直接实施，不要解释'。这次Claude花了{total_output} token做文本回复，大部分是解释说明。"
        return "建议: 如果不需要讨论，直接给出明确的实施指令，例如'修改XX文件的YY函数，实现ZZ功能'。"

    # 有修改操作 → 建议精确指定目标文件
    if changed_files:
        files_str = "、".join(changed_files[:3])
        if len(user_msg) > 300:
            return f"建议精简为: '修改 {files_str}，实现[具体功能]。直接改，不需要解释。' — 原prompt过长({len(user_msg)}字符)，明确文件路径可减少搜索成本。"
        else:
            return f"建议: '修改 {files_str}，[具体需求]。' — 预先指定目标文件路径，减少Claude自行搜索和阅读的token消耗。"

    # 只有搜索+阅读 = 探索性任务
    if searches or reads:
        if len(searches) > 3 or len(reads) > 5:
            return "建议: 探索性任务用'用Agent(Explore)帮我找到[目标]'比逐个搜索高效。或者先用grep/glob缩小范围，再具体读。"
        return "建议: 如果是了解代码结构，可以用'帮我理解XX模块的架构，重点关注YY'来聚焦。"

    # 大量bash命令
    if len(bashes) > 3:
        return "建议: 多个独立命令可以一条prompt说'并行执行以下命令: ...'，或合并到一个脚本中。"

    return f"建议: 用更具体的指令代替开放式描述，预先指定文件路径和期望行为。总成本${total_cost:.2f}。"


def find_costly_prompts(events):
    """找出高成本的对话轮次，附带实际产出和改进建议"""
    results = []

    i = 0
    while i < len(events):
        if events[i]["type"] != "user":
            i += 1
            continue

        user_msg = events[i]["text"]
        user_ts = events[i]["timestamp"]

        # 找后续所有assistant响应直到下一个user消息
        total_cost = 0
        total_tools = 0
        total_output = 0
        all_tool_calls = []
        j = i + 1
        while j < len(events) and events[j]["type"] == "assistant":
            total_cost += events[j].get("cost", 0)
            tc_list = events[j].get("tool_calls", [])
            total_tools += len(tc_list)
            total_output += events[j].get("output_tokens", 0)
            all_tool_calls.extend(tc_list)
            j += 1

        # 高成本: $1+（无论工具多少都分析）
        if total_cost > 1.0:
            prompt_preview = user_msg[:300]
            actions_summary = _summarize_actions(all_tool_calls)
            better_prompt = _generate_better_prompt(user_msg, all_tool_calls, total_cost, total_output)

            # 基础suggestion保留
            if total_tools < 2:
                suggestion = f"花了${total_cost:.2f}但仅{total_tools}次工具调用。大量token消耗在文本生成上。"
            elif len(user_msg) > 500:
                suggestion = f"prompt有{len(user_msg)}字符，成本${total_cost:.2f}。精简prompt可减少input token。"
            else:
                suggestion = f"成本${total_cost:.2f}，{total_tools}次工具调用，{total_output} output tokens。"

            results.append({
                "timestamp": user_ts,
                "prompt": prompt_preview,
                "cost": round(total_cost, 2),
                "tools": total_tools,
                "output_tokens": total_output,
                "actions": actions_summary,
                "better_prompt": better_prompt,
                "suggestion": suggestion,
            })

        i = j

    # 按成本排序，取top
    results.sort(key=lambda x: x["cost"], reverse=True)
    return results


def find_mergeable_prompts(events):
    """找出连续的短prompt，可以合并为一条更高效的指令"""
    results = []
    consecutive_short = []

    for ev in events:
        if ev["type"] == "user":
            if len(ev["text"]) < 100:
                consecutive_short.append(ev)
            else:
                if len(consecutive_short) >= 3:
                    prompts = [s["text"][:80] for s in consecutive_short[:5]]
                    results.append({
                        "timestamp": consecutive_short[0]["timestamp"],
                        "count": len(consecutive_short),
                        "prompts": prompts,
                        "suggestion": f"连续发了{len(consecutive_short)}条短指令，每条都会触发新的context加载。合并为一条完整的指令可以减少{len(consecutive_short)-1}次context重复加载的token消耗。",
                    })
                consecutive_short = []
        # assistant消息不重置计数

    if len(consecutive_short) >= 3:
        prompts = [s["text"][:80] for s in consecutive_short[:5]]
        results.append({
            "timestamp": consecutive_short[0]["timestamp"],
            "count": len(consecutive_short),
            "prompts": prompts,
            "suggestion": f"连续发了{len(consecutive_short)}条短指令。合并为一条可以减少context重复加载。",
        })

    return results


def analyze_sessions(days=30, max_sessions=20):
    """分析最近N天的会话，生成具体建议"""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    # 获取成本最高的会话优先分析
    db = sqlite3.connect(EFFICIENCY_DB)
    db.row_factory = sqlite3.Row
    sessions = db.execute(
        "SELECT session_id, project, date, total_cost_usd FROM session_summaries WHERE date >= ? ORDER BY total_cost_usd DESC LIMIT ?",
        (cutoff, max_sessions)
    ).fetchall()
    db.close()

    all_advice = {
        "edit_without_read": [],
        "parallel_opportunities": [],
        "costly_prompts": [],
        "mergeable_prompts": [],
        "wasted_efforts": [],
    }

    analyzed_sessions = []

    for sess in sessions:
        sid = sess["session_id"]
        project = sess["project"]

        # 找到JSONL文件
        jsonl_path = None
        for proj_dir in glob.glob(os.path.join(SESSIONS_DIR, "*")):
            candidate = os.path.join(proj_dir, f"{sid}.jsonl")
            if os.path.exists(candidate):
                jsonl_path = candidate
                break

        if not jsonl_path:
            continue

        parsed = parse_session_for_advice(jsonl_path)
        events = parsed["events"]
        if not events:
            continue

        analyzed_sessions.append({
            "session_id": sid,
            "project": project,
            "date": sess["date"],
            "cost": float(sess["total_cost_usd"]),
        })

        # 分析各维度
        ewr = find_edit_without_read(events)
        for item in ewr:
            item["session_id"] = sid[:8]
            item["project"] = project
        all_advice["edit_without_read"].extend(ewr)

        po = find_parallel_opportunities(events)
        for item in po:
            item["session_id"] = sid[:8]
            item["project"] = project
        all_advice["parallel_opportunities"].extend(po)

        cp = find_costly_prompts(events)
        for item in cp:
            item["session_id"] = sid[:8]
            item["project"] = project
        all_advice["costly_prompts"].extend(cp)

        mp = find_mergeable_prompts(events)
        for item in mp:
            item["session_id"] = sid[:8]
            item["project"] = project
        all_advice["mergeable_prompts"].extend(mp)

        wf = find_wasted_efforts(events, jsonl_path)
        for item in wf:
            item["session_id"] = sid[:8]
            item["project"] = project
        all_advice["wasted_efforts"].extend(wf)

    # 限制数量，按重要性排序
    all_advice["edit_without_read"] = all_advice["edit_without_read"][:10]
    all_advice["costly_prompts"] = sorted(all_advice["costly_prompts"], key=lambda x: x["cost"], reverse=True)[:10]
    all_advice["parallel_opportunities"] = all_advice["parallel_opportunities"][:10]
    all_advice["mergeable_prompts"] = all_advice["mergeable_prompts"][:5]
    all_advice["wasted_efforts"] = sorted(all_advice["wasted_efforts"], key=lambda x: x.get("timestamp", ""), reverse=True)[:15]

    # 总结统计
    summary = {
        "sessions_analyzed": len(analyzed_sessions),
        "edit_without_read_count": len(all_advice["edit_without_read"]),
        "parallel_opportunity_count": len(all_advice["parallel_opportunities"]),
        "costly_prompt_count": len(all_advice["costly_prompts"]),
        "mergeable_prompt_count": len(all_advice["mergeable_prompts"]),
        "wasted_effort_count": len(all_advice["wasted_efforts"]),
        "potential_savings": round(sum(cp["cost"] * 0.3 for cp in all_advice["costly_prompts"]), 2),  # 预估可节省30%
    }

    return {
        "summary": summary,
        "advice": all_advice,
        "sessions": analyzed_sessions[:10],
    }


def find_wasted_efforts(events, filepath):
    """找出Claude给出错误指引或无效内容的情况：
    1. 工具执行失败后重试（走弯路）
    2. 用户纠错（Claude做错了用户纠正）
    3. Claude自我纠正（承认错误）
    4. 同一文件反复修改（首次修改有误）
    """
    results = []

    # 需要完整解析JSONL，包含tool_result
    tool_uses = {}  # tool_use_id -> {name, input, timestamp, user_prompt}
    events_full = []

    correction_kw = ['不对', '错了', '不是这样', '重新', '回退', '撤销', '搞错', '弄错',
                     'wrong', 'revert', 'undo', '改回来', '不行', '有问题', '失败了', '没用']
    apology_kw = ['抱歉', '对不起', 'sorry', 'apologize', 'my mistake', '我的错',
                  '搞错了', '修正', '纠正']

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type", "")
            timestamp = data.get("timestamp", "")

            if msg_type == "assistant":
                msg = data.get("message", {})
                contents = msg.get("content", [])
                if not isinstance(contents, list):
                    continue

                for block in contents:
                    if not isinstance(block, dict):
                        continue

                    # 记录tool_use
                    if block.get("type") == "tool_use":
                        tid = block.get("id", "")
                        tool_uses[tid] = {
                            "name": block.get("name", ""),
                            "input": block.get("input", {}),
                            "timestamp": timestamp,
                        }

                    # Claude自我纠正
                    if block.get("type") == "text":
                        text = block.get("text", "")
                        text_lower = text.lower()[:500]
                        for kw in apology_kw:
                            if kw in text_lower:
                                # 找前面最近的user消息
                                user_prompt = ""
                                for ev in reversed(events_full):
                                    if ev.get("ev_type") == "user":
                                        user_prompt = ev.get("text", "")[:150]
                                        break
                                results.append({
                                    "type": "claude_correction",
                                    "type_zh": "Claude自我纠正",
                                    "timestamp": timestamp,
                                    "user_prompt": user_prompt,
                                    "detail": text[:200],
                                    "suggestion": "Claude承认了错误并重新尝试。原始prompt可能不够精确，导致首次理解偏差。",
                                })
                                break

                events_full.append({"ev_type": "assistant", "timestamp": timestamp})

            elif msg_type == "user":
                content = data.get("message", {}).get("content", "")
                user_text = ""
                tool_results_in_msg = []

                if isinstance(content, list):
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        if block.get("type") == "text":
                            user_text += block.get("text", "")
                        elif block.get("type") == "tool_result":
                            tid = block.get("tool_use_id", "")
                            is_err = block.get("is_error", False)
                            # 提取content文本
                            ct = ""
                            bc = block.get("content", "")
                            if isinstance(bc, list):
                                for sub in bc:
                                    if isinstance(sub, dict) and sub.get("type") == "text":
                                        ct += sub.get("text", "")
                            elif isinstance(bc, str):
                                ct = bc
                            tool_results_in_msg.append({
                                "tool_use_id": tid,
                                "is_error": is_err,
                                "content": ct,
                            })
                elif isinstance(content, str):
                    user_text = content

                # 检查tool_result错误
                for tr in tool_results_in_msg:
                    if not tr["is_error"]:
                        continue
                    tool_info = tool_uses.get(tr["tool_use_id"], {})
                    tool_name = tool_info.get("name", "?")
                    tool_input = tool_info.get("input", {})

                    # 跳过用户主动拒绝
                    if "permission denied by user" in tr["content"].lower():
                        continue

                    error_msg = tr["content"][:200]
                    cmd_detail = ""
                    if tool_name == "Bash":
                        cmd_detail = tool_input.get("command", "")[:100]
                    elif tool_name in ("Edit", "Write", "Read"):
                        cmd_detail = tool_input.get("file_path", "")
                    elif tool_name in ("Grep", "Glob"):
                        cmd_detail = tool_input.get("pattern", "")

                    # 找触发这次操作的user prompt
                    user_prompt = ""
                    for ev in reversed(events_full):
                        if ev.get("ev_type") == "user":
                            user_prompt = ev.get("text", "")[:150]
                            break

                    suggestion = ""
                    if "exit code" in error_msg.lower():
                        suggestion = f"{tool_name}执行报错。如果是命令拼写/路径错误，在prompt中提供精确路径可避免。如果是环境问题，先告知Claude当前环境配置。"
                    elif "not unique" in error_msg.lower() or "old_string" in error_msg.lower():
                        suggestion = "Edit的old_string不唯一导致失败。提供更多上下文或精确行号可避免。"
                    else:
                        suggestion = f"{tool_name}执行失败：{error_msg[:80]}。提前给出精确的文件路径和预期行为可减少试错。"

                    results.append({
                        "type": "tool_error",
                        "type_zh": "工具执行失败",
                        "timestamp": tool_info.get("timestamp", timestamp),
                        "tool": tool_name,
                        "command": cmd_detail,
                        "error": error_msg,
                        "user_prompt": user_prompt,
                        "suggestion": suggestion,
                    })

                # 检查用户纠错
                if user_text:
                    text_lower = user_text.lower()
                    for kw in correction_kw:
                        if kw in text_lower and 5 < len(user_text) < 500:
                            # 找前面Claude说了什么
                            claude_said = ""
                            for ev in reversed(events_full):
                                if ev.get("ev_type") == "assistant":
                                    break
                            results.append({
                                "type": "user_correction",
                                "type_zh": "用户纠错",
                                "timestamp": timestamp,
                                "user_prompt": user_text[:200],
                                "detail": f"你指出了问题: '{user_text[:100]}'",
                                "suggestion": "用户发现Claude理解有误需要纠正。在初始prompt中提供更具体的约束条件和预期结果，可减少误解。",
                            })
                            break

                events_full.append({"ev_type": "user", "text": user_text, "timestamp": timestamp})

    # 检查同文件反复修改
    edit_counts = {}  # file -> [timestamps]
    for tid, info in tool_uses.items():
        if info["name"] in ("Edit", "Write"):
            fp = info["input"].get("file_path", "")
            fname = os.path.basename(fp) if fp else ""
            if fname:
                if fname not in edit_counts:
                    edit_counts[fname] = []
                edit_counts[fname].append(info["timestamp"])

    for fname, ts_list in edit_counts.items():
        if len(ts_list) >= 4:
            results.append({
                "type": "repeated_edit",
                "type_zh": "反复修改同文件",
                "timestamp": ts_list[0],
                "detail": f"{fname} 被修改了{len(ts_list)}次",
                "suggestion": f"同一文件修改{len(ts_list)}次，说明首次修改可能不完整或方向有误。提前明确完整需求，一次性给出所有修改点，避免反复迭代。",
            })

    return results


def get_session_advice(session_id):
    """分析单个会话，返回最贵的几条prompt的改进建议"""
    # 找到JSONL文件
    jsonl_path = None
    for proj_dir in glob.glob(os.path.join(SESSIONS_DIR, "*")):
        candidate = os.path.join(proj_dir, f"{session_id}.jsonl")
        if os.path.exists(candidate):
            jsonl_path = candidate
            break

    if not jsonl_path:
        return []

    parsed = parse_session_for_advice(jsonl_path)
    events = parsed["events"]
    if not events:
        return []

    # 找这个会话中成本最高的3条prompt
    prompts = []
    i = 0
    while i < len(events):
        if events[i]["type"] != "user":
            i += 1
            continue

        user_msg = events[i]["text"]
        user_ts = events[i]["timestamp"]
        total_cost = 0
        total_output = 0
        all_tool_calls = []
        j = i + 1
        while j < len(events) and events[j]["type"] == "assistant":
            total_cost += events[j].get("cost", 0)
            all_tool_calls.extend(events[j].get("tool_calls", []))
            total_output += events[j].get("output_tokens", 0)
            j += 1

        if total_cost > 0.3:  # 只关注>$0.3的轮次
            actions_summary = _summarize_actions(all_tool_calls)
            better = _generate_better_prompt(user_msg, all_tool_calls, total_cost, total_output)
            prompts.append({
                "time": user_ts[11:16] if len(user_ts) > 16 else "",
                "prompt": user_msg[:120],
                "cost": round(total_cost, 2),
                "actions": actions_summary,
                "better_prompt": better,
            })
        i = j

    prompts.sort(key=lambda x: x["cost"], reverse=True)
    return prompts[:3]


if __name__ == "__main__":
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    result = analyze_sessions(days)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
