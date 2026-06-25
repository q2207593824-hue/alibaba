# -*- coding: utf-8 -*-
"""
属性填写模块
重构自: main_属性融合.py 中的 fill_single_attribute() / fill_all_attributes()
"""
import os
import json
import time
import random
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, StaleElementReferenceException

from app.core.settings import AttributeConfig, AttributeItemConfig, DATA_DIR
from app.core.logger import setup_logger

logger = setup_logger("attribute_filler")

HISTORY_FILE = os.path.join(DATA_DIR, "published_attribute_signatures.json")
_ALWAYS_SKIP_ATTRS = frozenset({"省份"})
# 日志中耗时偏高的属性：走 JS 快路径，减少反复 read DOM / 下拉等待
_SLOW_SINGLE_SEARCH_ATTRS = frozenset({
    "提供模具制作和样品制作服务",
    "宝石生成方式",
    "应用",
    "诞生石",
})
_SLOW_TAG_ATTRS = frozenset({"镀层厚度"})
_SLOW_INPUT_COMBO_ATTRS = frozenset({"宝石形状"})


def _is_skipped_attr(attr_name: str, attr_config: AttributeConfig) -> bool:
    return attr_name in _ALWAYS_SKIP_ATTRS or attr_name in (attr_config.skip_attrs or [])


@contextmanager
def _attribute_fast_context(driver):
    """属性阶段关闭 implicit wait，避免 find_element 每次阻塞数秒。"""
    old_wait = 3
    try:
        old_wait = driver.timeouts.implicit_wait
    except Exception:
        pass
    try:
        driver.implicitly_wait(0)
        yield
    finally:
        try:
            driver.implicitly_wait(old_wait)
        except Exception:
            pass


def prepare_attribute_section(driver) -> None:
    """商品编码填完后立即滚到属性区并展开折叠项。"""
    try:
        driver.execute_script(
            """
            const targets = ['struct-icbuCatProp', 'struct-catProp', 'struct-productAttributes'];
            for (const id of targets) {
              const el = document.getElementById(id);
              if (el) {
                el.scrollIntoView({block: 'start', behavior: 'instant'});
                break;
              }
            }
            const clickExpand = (text) => {
              for (const el of document.querySelectorAll(
                'a, span, button, .next-btn-text, .product-sub-title, .next-collapse-panel-title'
              )) {
                const t = (el.textContent || '').trim();
                if (!t || !t.includes(text)) continue;
                if (t.includes('展开') || t.includes('必填') || el.querySelector('.next-icon-arrow-down')) {
                  try { el.click(); } catch (e) {}
                }
              }
            };
            clickExpand('必填属性');
            clickExpand('其他属性');
            """
        )
        time.sleep(0.15)
    except Exception:
        pass
    _expand_attribute_sections(driver)


def _sum_numeric_timings(step_timings: Optional[Dict]) -> float:
    if not step_timings:
        return 0.0
    return round(
        sum(
            v for k, v in step_timings.items()
            if k != "总计" and isinstance(v, (int, float))
        ),
        2,
    )


def _append_attr_fill_record(
    fill_report: Optional[List[Dict[str, Any]]],
    *,
    attr_name: str,
    select_type: str,
    required: bool,
    phase: str,
    values: List[str],
    duration_s: float,
    status: str,
    verify: str = "pending",
    actual: Optional[List[str]] = None,
    error: Optional[str] = None,
    original: Optional[List[str]] = None,
    planned: Optional[List[str]] = None,
    final: Optional[List[str]] = None,
) -> None:
    if fill_report is None:
        return
    rec: Dict[str, Any] = {
        "attr_name": attr_name,
        "select_type": select_type,
        "required": required,
        "phase": phase,
        "values": list(values or []),
        "duration_s": round(duration_s, 3),
        "status": status,
        "verify": verify,
        "actual": list(actual or []),
        "error": error or "",
    }
    if original is not None:
        rec["original_values"] = list(original)
    if planned is not None:
        rec["planned_values"] = list(planned)
    if final is not None:
        rec["final_values"] = list(final)
    fill_report.append(rec)


def _set_attr_verify_on_report(
    fill_report: Optional[List[Dict[str, Any]]],
    attr_name: str,
    verify: str,
    actual: Optional[List[str]] = None,
    phase: str = "first_pass",
) -> None:
    if not fill_report:
        return
    for rec in reversed(fill_report):
        if rec.get("attr_name") == attr_name and rec.get("phase") == phase:
            rec["verify"] = verify
            if actual is not None:
                rec["actual"] = list(actual)
            return


def fill_all_attributes_with_diff(
    driver,
    attr_config: AttributeConfig,
    fill_report: Optional[List[Dict[str, Any]]] = None,
    acceptance_audit: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[str]]:
    """批量填写所有属性，支持 40% 差异规则。返回本次实际计划填入的值（供验收对比）。"""
    history_sigs = _load_history_signatures()

    valid_signature = None
    candidate = None
    for attempt in range(2):
        candidate = _generate_signature(attr_config)
        conflict = False
        for old_sig in history_sigs[-5:]:
            sim = _calculate_similarity(candidate, old_sig, attr_config.diff_compare_attrs)
            if sim >= 0.6:
                conflict = True
                logger.info(f"尝试{attempt + 1}：与历史产品相似度过高 ({sim:.2%})，重新生成...")
                break
        if not conflict:
            valid_signature = candidate
            break

    if valid_signature is None:
        logger.warning("多次尝试未满足40%差异要求，使用最后一次生成结果")
        valid_signature = candidate or {}

    prepare_attribute_section(driver)
    with _attribute_fast_context(driver):
        planned = _fill_all_attributes(
            driver,
            attr_config,
            pre_generated_values=valid_signature,
            fill_report=fill_report,
            acceptance_audit=acceptance_audit,
        )

    history_sigs.append(valid_signature)
    _save_history_signatures(history_sigs)
    return planned


def _generate_signature(attr_config: AttributeConfig) -> Dict[str, List[str]]:
    """生成属性签名（严格对齐老脚本：按 diff_compare_attrs 维度抽样）"""
    signature: Dict[str, List[str]] = {}
    for attr_name in attr_config.diff_compare_attrs:
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue

        values = item.values or []
        picked = _pick_fill_values(attr_config, attr_name, values)
        signature[attr_name] = sorted(picked) if picked else []

    return signature


def _calculate_similarity(sig1: Dict, sig2: Dict, diff_compare_attrs: List[str]) -> float:
    total_attrs = len(diff_compare_attrs)
    if total_attrs == 0:
        return 1.0
    same_count = 0
    for attr in diff_compare_attrs:
        if sig1.get(attr) == sig2.get(attr):
            same_count += 1
    return same_count / total_attrs


def _load_history_signatures() -> List[Dict]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_history_signatures(sigs: List[Dict]):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(sigs[-100:], f, ensure_ascii=False, indent=2)


def _collect_visible_attribute_containers(driver) -> set:
    """扫描页面上实际存在的属性区块 struct-p-*。"""
    try:
        ids = driver.execute_script(
            """
            const out = new Set();
            for (const el of document.querySelectorAll('[id^="struct-p-"]')) {
              if (!el.offsetParent) continue;
              const hasControl = el.querySelector(
                'input, textarea, .next-select, .sell-catProp-struct, .next-tag-group'
              );
              if (hasControl) out.add(el.id);
            }
            return [...out];
            """
        )
        return set(ids or [])
    except Exception:
        return set()


def _collect_all_attribute_containers(driver) -> set:
    """扫描 DOM 中全部属性区块（含折叠区），用于复制页预填检测与批量清空。"""
    try:
        ids = driver.execute_script(
            """
            const out = new Set();
            for (const el of document.querySelectorAll('[id^="struct-p-"]')) {
              const hasControl = el.querySelector(
                'input, textarea, .next-select, .sell-catProp-struct, .next-tag-group'
              );
              if (hasControl) out.add(el.id);
            }
            return [...out];
            """
        )
        return set(ids or [])
    except Exception:
        return set()


def _expand_attribute_sections(driver) -> None:
    """展开「其他属性」等折叠区，确保复制页预填项可被检测和清空。"""
    try:
        driver.execute_script(
            """
            document.querySelectorAll(
              '.product-sub-title-guide-balloon, .next-balloon, .compose-notice, .guide-layer'
            ).forEach(el => {
              el.style.display = 'none';
              el.style.visibility = 'hidden';
              if (el._tippy) el._tippy.hide();
            });
            const tryExpand = (keyword) => {
              for (const el of document.querySelectorAll(
                'a, span, button, .next-btn-text, .product-sub-title, .next-collapse-panel-title'
              )) {
                const t = (el.textContent || '').trim();
                if (!t || !t.includes(keyword)) continue;
                if (t.includes('展开') || t.includes('必填') || el.querySelector('.next-icon-arrow-down')) {
                  try { el.click(); } catch (e) {}
                }
              }
            };
            tryExpand('必填属性');
            tryExpand('其他属性');
            for (const el of document.querySelectorAll('a, span, button, .next-btn-text')) {
              const t = (el.textContent || '').trim();
              if (t === '展开') {
                try { el.click(); } catch (e) {}
              }
            }
            """
        )
        time.sleep(0.12)
    except Exception:
        pass


def _container_has_value_quick(driver, container_id: str) -> bool:
    """不依赖 select_type，快速判断容器是否有非占位内容。"""
    cid = str(container_id or "").strip()
    if not cid:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                if (!root) return false;
                const deny = (t) => {
                  const s = (t || '').trim().toLowerCase();
                  if (!s || s === 'a' || s === '1') return true;
                  return s.includes('请输入') || s.includes('请选择')
                    || s.includes('please enter') || s.includes('please select');
                };
                for (const tag of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
                  if (!deny(tag.textContent)) return true;
                }
                for (const inp of root.querySelectorAll('input, textarea')) {
                  if (inp.type === 'hidden') continue;
                  if (!deny(inp.value)) return true;
                }
                return false;
                """,
                cid,
            )
        )
    except Exception:
        return False


def _any_prefilled_batch(driver, container_ids: set) -> bool:
    """一次 JS 检测多个属性容器是否有预填值（避免逐字段 read DOM）。"""
    ids = [str(cid).strip() for cid in (container_ids or set()) if str(cid).strip()]
    if not ids:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const ids = arguments[0];
                const deny = (t) => {
                  const s = (t || '').trim().toLowerCase();
                  if (!s || s === 'a' || s === '1') return true;
                  return s.includes('请输入') || s.includes('请选择')
                    || s.includes('please enter') || s.includes('please select');
                };
                for (const id of ids) {
                  const root = document.getElementById(id);
                  if (!root) continue;
                  for (const tag of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
                    if (!deny(tag.textContent)) return true;
                  }
                  for (const inp of root.querySelectorAll('input, textarea')) {
                    if (inp.type === 'hidden') continue;
                    if (!deny(inp.value)) return true;
                  }
                }
                return false;
                """,
                ids,
            )
        )
    except Exception:
        return False


def _has_any_prefilled_attributes(
    driver,
    attr_config: AttributeConfig,
    container_ids: set,
) -> bool:
    relevant: set = set()
    for attr_name, item in attr_config.all_attributes.items():
        if _is_skipped_attr(attr_name, attr_config):
            continue
        cid = str(item.container_id or "").strip()
        if not cid or (container_ids and cid not in container_ids):
            continue
        relevant.add(cid)
    if container_ids:
        relevant.update(container_ids)
    return _any_prefilled_batch(driver, relevant)


def _clear_attribute_container_force(driver, container_id: str) -> bool:
    """强制清空单个属性：tag + input 全部清除（不区分 select_type）。"""
    cid = str(container_id or "").strip()
    if not cid:
        return False
    try:
        had_value = bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                if (!root) return false;
                let had = false;
                for (const tag of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
                  const t = (tag.textContent || '').trim();
                  if (t) had = true;
                }
                for (const inp of root.querySelectorAll('input, textarea')) {
                  if (inp.type === 'hidden') continue;
                  if ((inp.value || '').trim()) had = true;
                }
                for (let i = 0; i < 48; i++) {
                  const btn = root.querySelector(
                    '.next-tag-close-btn, .next-tag .next-tag-close, [class*="tag-close"], .next-icon-close'
                  );
                  if (!btn) break;
                  btn.click();
                }
                for (const inp of root.querySelectorAll('input, textarea')) {
                  if (inp.type === 'hidden') continue;
                  inp.focus();
                  const proto = inp.tagName === 'TEXTAREA'
                    ? HTMLTextAreaElement.prototype
                    : HTMLInputElement.prototype;
                  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                  setter.call(inp, '');
                  inp.dispatchEvent(new Event('input', {bubbles: true}));
                  inp.dispatchEvent(new Event('change', {bubbles: true}));
                  inp.dispatchEvent(new Event('blur', {bubbles: true}));
                }
                return had;
                """,
                cid,
            )
        )
        return had_value
    except Exception:
        return False


def _clear_all_visible_attributes(
    driver,
    attr_config: AttributeConfig,
    container_ids: set,
) -> int:
    """复制页：一次性 JS 批量清空全部属性区块（避免逐字段轮询）。"""
    skip_cids = set()
    for attr_name, item in attr_config.all_attributes.items():
        if _is_skipped_attr(attr_name, attr_config):
            cid = str(item.container_id or "").strip()
            if cid:
                skip_cids.add(cid)
    cids = [c for c in container_ids if c and c not in skip_cids]
    if not cids:
        return 0
    try:
        cleared_n = int(
            driver.execute_script(
                """
                let cleared = 0;
                for (const cid of arguments[0]) {
                  const root = document.getElementById(cid);
                  if (!root) continue;
                  let had = false;
                  for (const tag of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
                    if ((tag.textContent || '').trim()) { had = true; break; }
                  }
                  for (const inp of root.querySelectorAll('input, textarea')) {
                    if (inp.type !== 'hidden' && (inp.value || '').trim()) { had = true; break; }
                  }
                  if (!had) continue;
                  cleared++;
                  for (let i = 0; i < 48; i++) {
                    const btn = root.querySelector(
                      '.next-tag-close-btn, .next-tag .next-tag-close, [class*="tag-close"], '
                      + '.next-icon-close, .next-tag .next-icon-close'
                    );
                    if (!btn) break;
                    btn.click();
                  }
                  for (const inp of root.querySelectorAll('input, textarea')) {
                    if (inp.type === 'hidden') continue;
                    inp.focus();
                    const proto = inp.tagName === 'TEXTAREA'
                      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
                    setter.call(inp, '');
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    inp.dispatchEvent(new Event('change', {bubbles: true}));
                  }
                }
                return cleared;
                """,
                cids,
            )
            or 0
        )
        return cleared_n
    except Exception:
        return 0


def _hide_attribute_balloons_once(driver) -> None:
    try:
        driver.execute_script(
            """
            document.querySelectorAll(
              '.product-sub-title-guide-balloon, .next-balloon, .compose-notice, .guide-layer'
            ).forEach(el => {
              el.style.display = 'none';
              el.style.visibility = 'hidden';
              if (el._tippy) try { el._tippy.hide(); } catch (e) {}
            });
            """
        )
    except Exception:
        pass


def _join_input_values(values: List[str], sep: str = ", ") -> str:
    return sep.join(str(v).strip() for v in values if str(v).strip())


def _resolve_fill_count(attr_config: AttributeConfig, attr_name: str, pool: List[str]) -> int:
    """读取属性配置中的「填入数量」，与前端默认一致：未配置时为 1。"""
    count_rule = attr_config.count_rule or {}
    try:
        n = int(count_rule.get(attr_name, 1))
    except (TypeError, ValueError):
        n = 1
    n = max(1, n)
    if pool:
        n = min(n, len(pool))
    return n


def _pick_fill_values(
    attr_config: AttributeConfig,
    attr_name: str,
    original_values: List[str],
    actual_values: Optional[List[str]] = None,
) -> List[str]:
    """按 count_rule 严格抽取要填写的值列表。"""
    pool = [str(v).strip() for v in (original_values or []) if str(v).strip()]
    n = _resolve_fill_count(attr_config, attr_name, pool)
    if not pool:
        return []

    if actual_values is not None:
        prefer = [str(v).strip() for v in actual_values if str(v).strip()]
        if len(prefer) > n:
            return random.sample(prefer, n)
        if len(prefer) == n:
            return prefer
        if prefer:
            remaining = [v for v in pool if v not in prefer]
            need = n - len(prefer)
            if remaining and need > 0:
                extra = random.sample(remaining, min(need, len(remaining)))
                return prefer + extra
            return prefer
        # 预生成值为空时回退到随机抽取
        if n >= len(pool):
            return random.sample(pool, len(pool))
        return random.sample(pool, n)

    if n >= len(pool):
        return random.sample(pool, len(pool))
    return random.sample(pool, n)


def _set_input_value(driver, element, text: str) -> None:
    driver.execute_script(
        """
        const inp = arguments[0];
        const val = arguments[1];
        inp.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(inp, val);
        inp.dispatchEvent(new Event('input', {bubbles: true}));
        inp.dispatchEvent(new Event('change', {bubbles: true}));
        inp.blur();
        """,
        element,
        text,
    )


def _fill_input_in_container(driver, container_id: str, input_id: Optional[str], text: str) -> bool:
    """在属性容器内写入 input 值（兼容 React 受控组件）。"""
    if not str(text or "").strip():
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                const inputId = arguments[1];
                const val = arguments[2];
                if (!root) return false;
                let inp = null;
                if (inputId) {
                  inp = root.querySelector('#' + CSS.escape(inputId));
                }
                if (!inp) inp = root.querySelector('.sell-catProp-struct input, input[type=text], input:not([type=hidden])');
                if (!inp) return false;
                inp.scrollIntoView({block: 'center'});
                inp.focus();
                inp.click();
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                return (inp.value || '').trim().length > 0;
                """,
                container_id,
                str(input_id or "").strip(),
                str(text),
            )
        )
    except Exception:
        return False


def _norm_attr_text(text: str) -> str:
    return str(text or "").strip().lower()


def _normalize_value_set(values: List[str]) -> List[str]:
    return sorted({_norm_attr_text(v) for v in (values or []) if _norm_attr_text(v)})


def _flatten_comma_values(values: List[str]) -> List[str]:
    """将「Crystal, Rhinestone」这类配置拆成独立 token，便于与页面多 tag 对齐。"""
    out: List[str] = []
    for v in values or []:
        s = str(v or "").strip()
        if not s:
            continue
        parts = [p.strip() for p in s.replace("，", ",").split(",") if p.strip()]
        out.extend(parts if len(parts) > 1 else [s])
    return out


def _attr_token_match(a: str, b: str) -> bool:
    """属性值等价：忽略大小写、单复数、包含关系。"""
    x, y = _norm_attr_text(a), _norm_attr_text(b)
    if not x or not y:
        return False
    if x == y:
        return True
    if x.rstrip("s") == y.rstrip("s"):
        return True
    if x in y or y in x:
        return True
    return False


def _token_list(values: List[str]) -> List[str]:
    return _flatten_comma_values([str(v).strip() for v in (values or []) if str(v).strip()])


def _extra_values_not_in_target(actual: List[str], expected: List[str]) -> List[str]:
    """原值里不在目标列表中的词（需单独移除）。"""
    act = _token_list(actual)
    exp = _token_list(expected)
    return [a for a in act if not any(_attr_token_match(a, e) for e in exp)]


def _missing_target_values(actual: List[str], expected: List[str]) -> List[str]:
    """目标里有、页面上还没有的词（按目标顺序）。"""
    act = _token_list(actual)
    exp = _token_list(expected)
    missing: List[str] = []
    for e in expected:
        e = str(e).strip()
        if not e:
            continue
        if any(_attr_token_match(e, a) for a in act):
            continue
        if not any(_attr_token_match(e, m) for m in missing):
            missing.append(e)
    return missing


def _remove_extra_tags_from_container(
    driver,
    container_id: str,
    extras: List[str],
) -> None:
    """仅移除与目标不一致的 tag，保留已匹配的原值。"""
    cid = str(container_id or "").strip()
    extra_list = [str(v).strip() for v in (extras or []) if str(v).strip()]
    if not cid or not extra_list:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            const extras = arguments[1] || [];
            if (!root || !extras.length) return;
            const norm = (s) => (s || '').trim().toLowerCase();
            const match = (a, b) => {
              const x = norm(a), y = norm(b);
              return x && y && (x === y || x.includes(y) || y.includes(x));
            };
            const isExtra = (t) => extras.some((e) => match(t, e));
            for (let round = 0; round < extras.length + 4; round++) {
              let removed = false;
              for (const tag of root.querySelectorAll('.next-tag')) {
                const body = tag.querySelector('.next-tag-body, .next-tag-inner');
                const t = (body && (body.innerText || body.textContent) || '').trim();
                if (!t || !isExtra(t)) continue;
                const btn = tag.querySelector(
                  '.next-tag-close-btn, .next-tag .next-tag-close, [class*="tag-close"], '
                  + '.next-icon-close'
                );
                if (btn) { btn.click(); removed = true; break; }
              }
              if (!removed) break;
            }
            """,
            cid,
            extra_list,
        )
    except Exception:
        pass


def _clear_plain_input_field(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    short_sleep: float,
) -> None:
    """普通 input：清空输入框全部文字。"""
    cid = str(container_id or "").strip()
    if not cid:
        return
    inp = _locate_attribute_input(driver, wait, cid, input_id, scroll=False)
    if not inp:
        return
    _set_input_value(driver, inp, "")
    time.sleep(short_sleep)


def _prepare_field_before_fill(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    select_type: str,
    valid_values: List[str],
    short_sleep: float,
) -> tuple:
    """
    按字段准备填写：不做整段批量清空。
    返回 (仍需填写的词, 是否整字段跳过)。
    - 无原值 → 不清空，填全部目标
    - 原值与目标一致 → 跳过
    - input 有多余原值 → 清空 input 全部文字，再填全部目标
    - tag/single_search 有多余 → 只删多余 tag
    """
    vals = _dedupe_values([str(v).strip() for v in (valid_values or []) if str(v).strip()])
    if not vals:
        return [], True

    if _verify_attribute_values(driver, container_id, select_type, vals):
        return [], True

    actual = _read_attribute_actual(driver, container_id, select_type)
    if not actual:
        return vals, False

    is_combo = False
    extras = _extra_values_not_in_target(actual, vals)
    if extras:
        if select_type == "input":
            _clear_plain_input_field(
                driver, wait, container_id, input_id, short_sleep
            )
            return vals, False
        if select_type in ("tag", "single_search"):
            _remove_extra_tags_from_container(driver, container_id, extras)
        time.sleep(short_sleep)

    if _verify_attribute_values(driver, container_id, select_type, vals):
        return [], True

    actual = _read_attribute_actual(driver, container_id, select_type)
    to_fill = _missing_target_values(actual, vals)
    return to_fill, False


def _values_match(actual: List[str], expected: List[str]) -> bool:
    act = [str(v).strip() for v in (actual or []) if str(v).strip()]
    exp = [str(v).strip() for v in (expected or []) if str(v).strip()]
    if not exp and not act:
        return True
    act_flat = _flatten_comma_values(act)
    exp_flat = _flatten_comma_values(exp)
    if len(exp_flat) != len(act_flat):
        return False
    for e in exp_flat:
        if not any(_attr_token_match(e, a) for a in act_flat):
            return False
    for a in act_flat:
        if not any(_attr_token_match(a, e) for e in exp_flat):
            return False
    return True


def _read_attribute_values_js(driver, container_id: str, select_type: str) -> List[str]:
    """单次 JS 读取属性当前值（比 find_element 逐字段读快）。"""
    cid = str(container_id or "").strip()
    if not cid:
        return []
    try:
        raw = driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            const type = arguments[1] || '';
            if (!root) return [];
            const deny = (t) => {
              const s = (t || '').trim().toLowerCase();
              if (!s || s === 'a' || s === '1') return true;
              return s.includes('请输入') || s.includes('请选择');
            };
            const tags = [];
            const seen = new Set();
            for (const el of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
              const t = (el.innerText || el.textContent || '').trim();
              if (!t || deny(t)) continue;
              const key = t.toLowerCase();
              if (seen.has(key)) continue;
              seen.add(key);
              tags.push(t);
            }
            if (type === 'tag' || type === 'single_search') {
              if (tags.length) return tags;
            }
            const vals = [];
            for (const inp of root.querySelectorAll('input')) {
              const v = (inp.value || '').trim();
              if (v && !deny(v) && !vals.includes(v)) vals.push(v);
            }
            if (type === 'input') {
              if (vals.length === 1 && vals[0].includes(',')) {
                return vals[0].replace(/，/g, ',').split(',').map(s => s.trim()).filter(Boolean);
              }
              return vals;
            }
            return tags.length ? tags : vals;
            """,
            cid,
            select_type,
        )
        return [str(v).strip() for v in (raw or []) if str(v).strip()]
    except Exception:
        return []


def _clear_tags_js_only(driver, container_id: str) -> None:
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            if (!root) return;
            for (let i = 0; i < 24; i++) {
              const btn = root.querySelector(
                '.next-tag-close-btn, .next-tag .next-tag-close, [class*="tag-close"]'
              );
              if (!btn) break;
              btn.click();
            }
            for (const inp of root.querySelectorAll('input, textarea')) {
              if (inp.type === 'hidden') continue;
              inp.focus();
              const proto = inp.tagName === 'TEXTAREA'
                ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
              const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
              setter.call(inp, '');
              inp.dispatchEvent(new Event('input', {bubbles: true}));
            }
            """,
            cid,
        )
    except Exception:
        pass


def _fill_tags_batch_js(
    driver,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
) -> bool:
    vals = [str(v).strip() for v in values if str(v).strip()]
    cid = str(container_id or "").strip()
    if not cid or not vals:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                const inputId = arguments[1];
                const values = arguments[2];
                if (!root) return false;
                let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
                if (!inp) {
                  inp = root.querySelector(
                    '.next-input input, .sell-catProp-struct input, input:not([type=hidden])'
                  );
                }
                if (!inp) return false;
                root.scrollIntoView({block: 'nearest'});
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                for (const val of values) {
                  inp.click();
                  inp.focus();
                  setter.call(inp, val);
                  inp.dispatchEvent(new Event('input', {bubbles: true}));
                  inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
                  inp.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
                }
                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                return true;
                """,
                cid,
                str(input_id or "").strip(),
                vals,
            )
        )
    except Exception:
        return False


def _dedupe_values(values: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for v in values:
        key = _norm_attr_text(v)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _fill_single_search_attr_fast(
    driver,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    input_selector: str,
    short_sleep: float,
) -> bool:
    """single_search 快路径：JS 填值 + 一次校验，失败再兜底一次。"""
    values = _dedupe_values(values)
    _clear_tags_js_only(driver, container_id)
    for value in values:
        if not _fill_combo_select_js(driver, container_id, input_id, value):
            _fill_single_search_value(
                driver, WebDriverWait(driver, 0.5), container_id, input_id,
                value, input_selector, short_sleep,
            )
    actual = _read_attribute_values_js(driver, container_id, "single_search")
    if all(_single_search_value_matched(actual, v) for v in values):
        return True
    _clear_tags_js_only(driver, container_id)
    for value in values:
        _fill_combo_select_js(driver, container_id, input_id, value)
    actual = _read_attribute_values_js(driver, container_id, "single_search")
    return all(_single_search_value_matched(actual, v) for v in values)


def _fill_input_combo_fast(
    driver,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    short_sleep: float,
) -> bool:
    _clear_tags_js_only(driver, container_id)
    for value in values:
        _fill_combo_select_js(driver, container_id, input_id, value)
        time.sleep(short_sleep)
    actual = _read_attribute_values_js(driver, container_id, "input")
    if _values_match(actual, values):
        return True
    _clear_tags_js_only(driver, container_id)
    for value in values:
        _fill_combo_select_js(driver, container_id, input_id, value)
    actual = _read_attribute_values_js(driver, container_id, "input")
    return _values_match(actual, values)


def _scroll_attribute_container(driver, container_id: str) -> None:
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            "const el=document.getElementById(arguments[0]);"
            "if(el)el.scrollIntoView({block:'center',behavior:'instant'});",
            cid,
        )
        time.sleep(0.08)
    except Exception:
        pass


def _attribute_timing(attr_config: AttributeConfig, is_required: bool) -> tuple:
    """属性阶段节奏：必填略慢、整体目标约 50–60 秒。"""
    base_wait = float(attr_config.attr_wait_time or 2)
    base_short = float(attr_config.short_sleep or 0.05)
    base_norm = float(attr_config.normal_sleep or 0.1)
    if is_required:
        return (
            min(1.2, max(0.85, base_wait * 0.5)),
            min(0.14, max(0.10, base_short * 2)),
            min(0.22, max(0.15, base_norm * 1.6)),
        )
    return (
        min(0.85, max(0.55, base_wait * 0.35)),
        min(0.12, max(0.08, base_short * 1.6)),
        min(0.18, max(0.12, base_norm * 1.3)),
    )


def _read_attribute_actual(
    driver,
    container_id: str,
    select_type: str,
) -> List[str]:
    actual = _read_attribute_values_js(driver, container_id, select_type)
    if actual:
        cleaned = [v for v in actual if not _is_placeholder_value(v)]
        if cleaned:
            return cleaned
    raw = read_attribute_from_dom(driver, container_id, select_type)
    return [v for v in raw if not _is_placeholder_value(v)]


def _wait_attribute_committed(
    driver,
    container_id: str,
    select_type: str,
    expected: List[str],
    timeout: float = 1.0,
) -> bool:
    deadline = time.time() + max(0.2, timeout)
    while time.time() < deadline:
        if _verify_attribute_values(driver, container_id, select_type, expected):
            return True
        time.sleep(0.08)
    return _verify_attribute_values(driver, container_id, select_type, expected)


def _verify_attribute_values(
    driver,
    container_id: str,
    select_type: str,
    expected: List[str],
) -> bool:
    expected = [str(v).strip() for v in (expected or []) if str(v).strip()]
    if not expected:
        return True
    actual = _read_attribute_actual(driver, container_id, select_type)
    if select_type == "single_search":
        return all(_single_search_value_matched(actual, v) for v in expected)
    return _values_match(actual, expected)


def _one_value_committed(
    driver,
    container_id: str,
    select_type: str,
    value: str,
) -> bool:
    val = str(value or "").strip()
    if not val:
        return True
    if select_type == "single_search":
        actual = _read_attribute_actual(driver, container_id, select_type)
        return _single_search_value_matched(actual, val)
    if select_type == "tag":
        actual = _read_attribute_actual(driver, container_id, "tag")
        return any(_norm_attr_text(val) == _norm_attr_text(a) for a in actual)
    if select_type == "input":
        actual = _read_attribute_actual(driver, container_id, "input")
        if _values_match(actual, [val]):
            return True
        try:
            container = driver.find_element(By.ID, container_id)
            for inp in container.find_elements(By.CSS_SELECTOR, "input"):
                raw = str(inp.get_attribute("value") or "").strip()
                if not raw:
                    continue
                if _norm_attr_text(val) in _norm_attr_text(raw):
                    return True
                parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
                if any(_norm_attr_text(val) == _norm_attr_text(p) for p in parts):
                    return True
        except Exception:
            pass
        return False
    actual = _read_attribute_actual(driver, container_id, select_type)
    return _values_match(actual, [val])


def _wait_one_value_committed(
    driver,
    container_id: str,
    select_type: str,
    value: str,
    timeout: float = 1.2,
) -> bool:
    deadline = time.time() + max(0.25, timeout)
    while time.time() < deadline:
        if _one_value_committed(driver, container_id, select_type, value):
            return True
        time.sleep(0.08)
    return _one_value_committed(driver, container_id, select_type, value)


def _wait_input_separator_visible(
    driver,
    container_id: str,
    values_so_far: List[str],
    timeout: float = 1.2,
) -> bool:
    """plain input 多词：当前词输入后出现逗号分隔符再继续下一词。"""
    if len(values_so_far) < 1:
        return True
    prefix = _join_input_values(values_so_far)
    deadline = time.time() + max(0.25, timeout)
    while time.time() < deadline:
        try:
            container = driver.find_element(By.ID, container_id)
            for inp in container.find_elements(By.CSS_SELECTOR, "input"):
                raw = str(inp.get_attribute("value") or "").strip()
                if not raw:
                    continue
                if raw.endswith(",") or raw.endswith("，"):
                    return True
                if _norm_attr_text(raw) == _norm_attr_text(prefix):
                    return True
                if _norm_attr_text(prefix) in _norm_attr_text(raw):
                    return True
        except Exception:
            pass
        time.sleep(0.08)
    return False


def _focus_combo_multiselect(driver, container_id: str, input_id: Optional[str]) -> None:
    """combo 多选：点击选择器并聚焦输入框，便于填第二词及之后。"""
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            const inputId = arguments[1];
            if (!root) return;
            const sel = root.querySelector(
              '.next-select-inner, .next-select-multiple, .next-select, .next-select-trigger'
            );
            if (sel) sel.click();
            const em = root.querySelector('.next-select .next-select-values, .next-select-multiple');
            if (em) em.click();
            let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
            if (!inp) {
              inp = root.querySelector(
                '.next-select-multiple input, .next-select .next-input input, '
                + '.next-select input, input:not([type=hidden])'
              );
            }
            if (inp) { inp.click(); inp.focus(); }
            """,
            cid,
            str(input_id or "").strip(),
        )
    except Exception:
        pass


def _combo_value_committed(
    driver,
    container_id: str,
    value: str,
    before_tags: List[str],
) -> bool:
    """combo 多选：确认目标词已作为 tag 落盘（且为本轮新增）。"""
    val = str(value or "").strip()
    if not val:
        return True
    after_tags = _combo_tag_values(driver, container_id)
    if not any(_attr_token_match(val, t) for t in after_tags):
        return False
    if any(_attr_token_match(val, t) for t in before_tags):
        return True
    return len(after_tags) > len(before_tags)


def _combo_tags_match_planned(driver, container_id: str, planned: List[str]) -> bool:
    current = _combo_tag_values(driver, container_id)
    return _values_match(current, planned)


def _clear_combo_input_field(driver, container_id: str, input_id: Optional[str]) -> None:
    """清空 combo 输入框文字，保留已有 tag。"""
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            const inputId = arguments[1];
            if (!root) return;
            let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
            if (!inp) {
              inp = root.querySelector(
                '.next-select input, .next-input input, .sell-catProp-struct input, input:not([type=hidden])'
              );
            }
            if (!inp) return;
            inp.click();
            inp.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(inp, '');
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.dispatchEvent(new Event('change', {bubbles: true}));
            """,
            cid,
            str(input_id or "").strip(),
        )
    except Exception:
        pass


def _click_combo_dropdown_option(driver, value: str) -> bool:
    val = str(value or "").strip()
    if not val:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const val = arguments[0];
                const norm = (s) => (s || '').trim().toLowerCase();
                const match = (a, b) => {
                  const x = norm(a), y = norm(b);
                  return x && y && (x === y || x.includes(y) || y.includes(x));
                };
                const sels = [
                  '.next-overlay-wrapper.opened .next-menu-item',
                  '.next-overlay-wrapper.opened .options-item',
                  '.next-overlay-wrapper.opened [role=option]',
                  '.next-select-menu-item',
                  '.next-menu-item',
                ];
                for (const sel of sels) {
                  for (const opt of document.querySelectorAll(sel)) {
                    if (!opt.offsetParent) continue;
                    const t = (opt.innerText || opt.textContent || '').trim();
                    if (match(t, val)) {
                      opt.click();
                      return true;
                    }
                  }
                }
                return false;
                """,
                val,
            )
        )
    except Exception:
        return False


def _combo_tag_values(driver, container_id: str) -> List[str]:
    return _read_attribute_actual(driver, container_id, "input")


def _fill_combo_input_one_value(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    value: str,
    short_sleep: float,
    *,
    scroll: bool = True,
) -> bool:
    """combo input 逐词：聚焦 → 清空输入框 → 搜索 → 选中 → 等 tag 落盘。"""
    val = str(value or "").strip()
    if not val:
        return True
    before_tags = _combo_tag_values(driver, container_id)
    if any(_attr_token_match(val, t) for t in before_tags):
        return True

    type_wait = max(0.35, short_sleep * 2)
    for attempt in range(2):
        if attempt > 0:
            time.sleep(short_sleep)
        _focus_combo_multiselect(driver, container_id, input_id)
        time.sleep(short_sleep)
        _clear_combo_input_field(driver, container_id, input_id)
        time.sleep(short_sleep)

        inp = _locate_attribute_input(driver, wait, container_id, input_id, scroll=scroll)
        if inp:
            try:
                inp.click()
                time.sleep(0.05)
                inp.send_keys(Keys.CONTROL, "a")
                inp.send_keys(Keys.BACKSPACE)
                inp.send_keys(val)
                time.sleep(type_wait)
                if _click_combo_dropdown_option(driver, val):
                    time.sleep(short_sleep)
                    if _combo_value_committed(driver, container_id, val, before_tags):
                        return True
                if _select_dropdown_option(
                    driver, wait, "", val, "single_search", timeout=1.0
                ):
                    time.sleep(short_sleep)
                    if _combo_value_committed(driver, container_id, val, before_tags):
                        return True
                inp.send_keys(Keys.ARROW_DOWN)
                time.sleep(0.05)
                inp.send_keys(Keys.ENTER)
                time.sleep(short_sleep)
                if _combo_value_committed(driver, container_id, val, before_tags):
                    return True
                driver.execute_script("arguments[0].blur();", inp)
                time.sleep(short_sleep)
                if _combo_value_committed(driver, container_id, val, before_tags):
                    return True
            except StaleElementReferenceException:
                inp = None
            except Exception:
                pass

        if _fill_combo_select_js(driver, container_id, input_id, val):
            time.sleep(short_sleep)
            if _combo_value_committed(driver, container_id, val, before_tags):
                return True
            _click_combo_dropdown_option(driver, val)
            time.sleep(short_sleep)
            if _combo_value_committed(driver, container_id, val, before_tags):
                return True

    deadline = time.time() + 2.5
    while time.time() < deadline:
        if _combo_value_committed(driver, container_id, val, before_tags):
            return True
        time.sleep(0.08)
    return _combo_value_committed(driver, container_id, val, before_tags)


def _fill_one_combo_or_search_value(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    value: str,
    input_selector: str,
    short_sleep: float,
    *,
    scroll: bool = True,
    is_combo_input: bool = False,
) -> None:
    """combo / single_search：搜索并选中一个词。"""
    val = str(value or "").strip()
    if not val:
        return
    if is_combo_input:
        _fill_combo_input_one_value(
            driver, wait, container_id, input_id, val, short_sleep, scroll=scroll
        )
        return
    if not _fill_combo_select_js(driver, container_id, input_id, val):
        _fill_single_search_value(
            driver, wait, container_id, input_id, val, input_selector, short_sleep,
            verify_after=False, scroll=scroll,
        )
    time.sleep(short_sleep)


def _fill_plain_input_sequential(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    short_sleep: float,
    normal_sleep: float,
    *,
    scroll: bool = True,
) -> bool:
    """plain input：单词直接写入；多词用逗号连接，如 big,day,one。"""
    vals = [str(v).strip() for v in values if str(v).strip()]
    if not vals:
        return True
    if _verify_attribute_values(driver, container_id, "input", vals):
        return True
    inp = _locate_attribute_input(driver, wait, container_id, input_id, scroll=scroll)
    if not inp:
        return False
    try:
        text = vals[0] if len(vals) == 1 else ",".join(vals)
        _set_input_value(driver, inp, text)
        time.sleep(normal_sleep)
        driver.execute_script("arguments[0].blur();", inp)
        time.sleep(short_sleep)
        return _verify_attribute_values(driver, container_id, "input", vals)
    except Exception as exc:
        logger.warning(f"input 填写失败 {vals!r}: {exc}")
        return False


def _fill_values_sequential(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    select_type: str,
    values: List[str],
    input_selector: str,
    must_clear: bool,
    short_sleep: float,
    normal_sleep: float,
    *,
    scroll_to_field: bool = True,
) -> bool:
    """严格逐词：当前词选中/落盘后才填下一个；属性内不乱序、不批量。"""
    vals = _dedupe_values([str(v).strip() for v in values if str(v).strip()])
    if not vals:
        return True

    to_fill, skip_field = _prepare_field_before_fill(
        driver, wait, container_id, input_id, select_type, vals, short_sleep,
    )
    if skip_field:
        return True
    if not to_fill:
        return _verify_attribute_values(driver, container_id, select_type, vals)

    if select_type == "input":
        return _fill_plain_input_sequential(
            driver, wait, container_id, input_id, vals,
            short_sleep, normal_sleep, scroll=scroll_to_field,
        )

    max_attempts = 2
    for idx, value in enumerate(to_fill):
        if _verify_attribute_values(driver, container_id, select_type, vals):
            return True
        current = _read_attribute_actual(driver, container_id, select_type)
        if any(_attr_token_match(value, c) for c in current):
            continue

        committed = False
        for attempt in range(max_attempts):
            if attempt > 0:
                time.sleep(short_sleep)
            if select_type == "tag":
                _fill_tag_value(
                    driver, wait, container_id, input_id, value, short_sleep,
                    skip_existing_check=True, verify_after=False, scroll=scroll_to_field,
                )
            elif select_type == "single_search":
                _fill_one_combo_or_search_value(
                    driver, wait, container_id, input_id, value, input_selector, short_sleep,
                    scroll=scroll_to_field, is_combo_input=False,
                )
            else:
                return False

            time.sleep(short_sleep)
            committed = _wait_one_value_committed(
                driver, container_id, select_type, value, timeout=1.5
            )
            if committed:
                break
        if not committed:
            if _verify_attribute_values(driver, container_id, select_type, vals):
                return True
            logger.warning(f"{select_type} 词未落盘，停止本属性后续填写: {value!r}")
            return False
        time.sleep(normal_sleep)
    return _verify_attribute_values(driver, container_id, select_type, vals)


def _fill_input_reliable(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    input_selector: str,
    must_clear: bool,
    short_sleep: float,
    normal_sleep: float = 0.15,
    *,
    verify_after: bool = True,
    scroll_to_field: bool = True,
) -> bool:
    ok = _fill_values_sequential(
        driver, wait, container_id, input_id, "input", values, input_selector,
        must_clear, short_sleep, normal_sleep, scroll_to_field=scroll_to_field,
    )
    if not verify_after:
        return ok or _verify_attribute_values(driver, container_id, "input", values)
    return ok and _verify_attribute_values(driver, container_id, "input", values)


def _fill_tag_reliable(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    must_clear: bool,
    short_sleep: float,
    normal_sleep: float = 0.15,
    *,
    verify_after: bool = True,
    scroll_to_field: bool = True,
) -> bool:
    ok = _fill_values_sequential(
        driver, wait, container_id, input_id, "tag", values, input_selector="",
        must_clear=must_clear, short_sleep=short_sleep, normal_sleep=normal_sleep,
        scroll_to_field=scroll_to_field,
    )
    if not verify_after:
        return ok or _verify_attribute_values(driver, container_id, "tag", values)
    return ok and _verify_attribute_values(driver, container_id, "tag", values)


def _fill_single_search_reliable(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    values: List[str],
    input_selector: str,
    must_clear: bool,
    short_sleep: float,
    normal_sleep: float = 0.15,
    *,
    verify_after: bool = True,
    scroll_to_field: bool = True,
) -> bool:
    ok = _fill_values_sequential(
        driver, wait, container_id, input_id, "single_search", values, input_selector,
        must_clear, short_sleep, normal_sleep, scroll_to_field=scroll_to_field,
    )
    if not verify_after:
        return ok or _verify_attribute_values(
            driver, container_id, "single_search", values
        )
    return ok and _verify_attribute_values(driver, container_id, "single_search", values)


def _single_search_value_matched(actual: List[str], expected: str) -> bool:
    target = _norm_attr_text(expected)
    if not target:
        return False
    for item in actual:
        if _attr_token_match(item, expected):
            return True
    return False


def _clear_tags_in_container(driver, container_id: str) -> None:
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            if (!root) return;
            for (let i = 0; i < 48; i++) {
              const btn = root.querySelector(
                '.next-tag-close-btn, .next-tag .next-tag-close, [class*="tag-close"], '
                + '.next-icon-close, .next-tag .next-icon-close'
              );
              if (!btn) break;
              btn.click();
            }
            """,
            cid,
        )
    except Exception:
        pass


def _clear_tags_until_empty(driver, container_id: str, *, max_rounds: int = 24) -> None:
    """反复点关闭 tag，直到容器内无 tag（复制页预填残留）。"""
    cid = str(container_id or "").strip()
    if not cid:
        return
    for _ in range(max_rounds):
        tags = _read_attribute_actual(driver, cid, "tag")
        if not tags:
            return
        _clear_tags_in_container(driver, cid)
        time.sleep(0.06)
    _clear_attribute_container_force(driver, cid)


def _clear_inputs_in_container(driver, container_id: str) -> None:
    cid = str(container_id or "").strip()
    if not cid:
        return
    try:
        driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            if (!root) return;
            for (const inp of root.querySelectorAll('input, textarea')) {
              if (inp.type === 'hidden') continue;
              inp.focus();
              const proto = inp.tagName === 'TEXTAREA'
                ? HTMLTextAreaElement.prototype
                : HTMLInputElement.prototype;
              const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
              setter.call(inp, '');
              inp.dispatchEvent(new Event('input', {bubbles: true}));
              inp.dispatchEvent(new Event('change', {bubbles: true}));
            }
            """,
            cid,
        )
    except Exception:
        pass


def _clear_attribute_container(driver, container_id: str, select_type: str) -> None:
    """复制页：JS 批量清空 tag 与 input，避免键盘清空对 React 无效。"""
    if select_type in ("tag", "single_search"):
        _clear_tags_in_container(driver, container_id)
    _clear_inputs_in_container(driver, container_id)


def _clear_single_search_before_fill(driver, container_id: str) -> None:
    """single_search 多选标签：移除已有 tag，避免复制页预填或重复提交。"""
    _clear_attribute_container(driver, container_id, "single_search")
    time.sleep(0.05)


def _attribute_input_selectors(container_id: str, input_id: Optional[str]) -> List[str]:
    cid = str(container_id or "").strip()
    if not cid:
        return []
    selectors: List[str] = []
    if str(input_id or "").strip():
        selectors.append(f"#{cid} input#{input_id}")
    selectors.extend([
        f"#{cid} .sell-catProp-struct .next-input input",
        f"#{cid} .next-select .next-input input",
        f"#{cid} .next-select input",
        f"#{cid} .next-input input",
        f"#{cid} input[type='text']",
        f"#{cid} input:not([type='hidden'])",
    ])
    return selectors


def _container_uses_combo_select(driver, container_id: str) -> bool:
    cid = str(container_id or "").strip()
    if not cid:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                if (!root) return false;
                if (root.querySelector(
                  '.next-select, .sell-o-select, .next-select-multiple, '
                  + '.sell-catProp-struct .next-select'
                )) return true;
                const tags = root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner');
                const inp = root.querySelector(
                  '.next-select-multiple input, .next-select input, .next-input input'
                );
                return tags.length > 0 && !!inp;
                """,
                cid,
            )
        )
    except Exception:
        return False


def _fill_combo_select_js(
    driver,
    container_id: str,
    input_id: Optional[str],
    value: str,
) -> bool:
    """下拉组合框快速填写：点选下拉项（single_search / 请输入或者选择 类 input）。"""
    val = str(value or "").strip()
    cid = str(container_id or "").strip()
    if not val or not cid:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                const inputId = arguments[1];
                const val = arguments[2];
                if (!root) return false;
                const norm = (s) => (s || '').trim().toLowerCase();
                const match = (a, b) => {
                  const x = norm(a), y = norm(b);
                  return x && y && (x === y || x.includes(y) || y.includes(x));
                };
                let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
                if (!inp) {
                  inp = root.querySelector(
                    '.next-select input, .sell-catProp-struct input, .next-input input, input:not([type=hidden])'
                  );
                }
                if (!inp) return false;
                root.scrollIntoView({block: 'center'});
                inp.click();
                inp.focus();
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                const tryClick = (opt) => {
                  const t = (opt.innerText || opt.textContent || '').trim();
                  if (!t || !opt.offsetParent) return false;
                  if (!match(t, val)) return false;
                  opt.click();
                  inp.dispatchEvent(new Event('blur', {bubbles: true}));
                  return true;
                };
                for (const opt of root.querySelectorAll(
                  '.next-menu-item, .options-item, [role=option], .next-select-menu-item'
                )) {
                  if (tryClick(opt)) return true;
                }
                const menuSels = [
                  '.next-overlay-wrapper.opened .next-menu-item',
                  '.next-overlay-wrapper.opened .options-item',
                  '.next-overlay-wrapper.opened [role=option]',
                ];
                for (const sel of menuSels) {
                  for (const opt of document.querySelectorAll(sel)) {
                    if (tryClick(opt)) return true;
                  }
                }
                inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', code: 'Enter', bubbles: true}));
                inp.dispatchEvent(new KeyboardEvent('keyup', {key: 'Enter', code: 'Enter', bubbles: true}));
                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                return match(inp.value, val);
                """,
                cid,
                str(input_id or "").strip(),
                val,
            )
        )
    except Exception:
        return False


def _container_exists(driver, container_id: str) -> bool:
    cid = str(container_id or "").strip()
    if not cid:
        return False
    try:
        return bool(
            driver.execute_script("return !!document.getElementById(arguments[0]);", cid)
        )
    except Exception:
        return False


def _fill_autocomplete_js(
    driver,
    container_id: str,
    input_id: Optional[str],
    value: str,
) -> bool:
    """auto_complete 快速填写：JS 设值并点选下拉项。"""
    val = str(value or "").strip()
    cid = str(container_id or "").strip()
    if not val or not cid:
        return False
    try:
        return bool(
            driver.execute_script(
                """
                const root = document.getElementById(arguments[0]);
                const inputId = arguments[1];
                const val = arguments[2];
                if (!root) return false;
                const norm = (s) => (s || '').trim().toLowerCase();
                const match = (a, b) => {
                  const x = norm(a), y = norm(b);
                  return x && y && (x === y || x.includes(y) || y.includes(x));
                };
                let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
                if (!inp) {
                  inp = root.querySelector(
                    '.next-input input, .sell-catProp-struct input, input:not([type=hidden])'
                  );
                }
                if (!inp) return false;
                root.scrollIntoView({block: 'center'});
                inp.click();
                inp.focus();
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                setter.call(inp, val);
                inp.dispatchEvent(new Event('input', {bubbles: true}));
                inp.dispatchEvent(new Event('change', {bubbles: true}));
                const optSels = [
                  '.next-auto-complete-option',
                  '[class*="auto-complete-option"]',
                  '.next-overlay-wrapper.opened .next-menu-item',
                ];
                for (const sel of optSels) {
                  for (const opt of document.querySelectorAll(sel)) {
                    const t = (opt.innerText || opt.textContent || '').trim();
                    if (!t || !opt.offsetParent) continue;
                    if (match(t, val)) {
                      opt.click();
                      inp.dispatchEvent(new Event('blur', {bubbles: true}));
                      return true;
                    }
                  }
                }
                inp.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}));
                inp.dispatchEvent(new Event('blur', {bubbles: true}));
                return match(inp.value, val);
                """,
                cid,
                str(input_id or "").strip(),
                val,
            )
        )
    except Exception:
        return False


def _locate_attribute_input(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    *,
    scroll: bool = True,
):
    if not _container_exists(driver, container_id):
        return None
    short_wait = WebDriverWait(driver, 0.2)
    for selector in _attribute_input_selectors(container_id, input_id):
        try:
            return short_wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
        except TimeoutException:
            continue
    try:
        el = driver.execute_script(
            """
            const root = document.getElementById(arguments[0]);
            const inputId = arguments[1];
            const doScroll = arguments[2];
            if (!root) return null;
            let inp = inputId ? root.querySelector('#' + CSS.escape(inputId)) : null;
            if (!inp) {
              inp = root.querySelector(
                '.sell-catProp-struct input, .next-select input, .next-input input, input:not([type=hidden])'
              );
            }
            if (!inp) return null;
            if (doScroll) inp.scrollIntoView({block: 'center'});
            return inp;
            """,
            container_id,
            str(input_id or "").strip(),
            bool(scroll),
        )
        return el
    except Exception:
        return None


def _fill_single_search_value(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    value: str,
    input_selector: str,
    short_sleep: float = 0.05,
    *,
    verify_after: bool = True,
    scroll: bool = True,
) -> bool:
    """填写 single_search 下拉（JS 点选 + 短超时兜底）。"""
    val = str(value or "").strip()
    if not val:
        return False

    def _filled() -> bool:
        actual = read_attribute_from_dom(driver, container_id, "single_search")
        return _single_search_value_matched(actual, val)

    if verify_after and _filled():
        return True

    if _fill_combo_select_js(driver, container_id, input_id, val):
        time.sleep(short_sleep)
        if not verify_after or _filled():
            return True

    fast_wait = WebDriverWait(driver, 0.8)
    attribute_input = _locate_attribute_input(
        driver, fast_wait, container_id, input_id, scroll=scroll
    )
    if attribute_input:
        try:
            attribute_input.click()
            attribute_input.send_keys(val)
            time.sleep(0.08)
            if _select_dropdown_option(driver, fast_wait, "", val, "single_search", timeout=0.8):
                time.sleep(short_sleep)
                if not verify_after or _filled():
                    return True
            attribute_input.send_keys(Keys.ENTER)
            time.sleep(short_sleep)
            return True if not verify_after else _filled()
        except Exception:
            pass

    return True if not verify_after else _filled()


def _fill_tag_value(
    driver,
    wait,
    container_id: str,
    input_id: Optional[str],
    value: str,
    short_sleep: float,
    *,
    skip_existing_check: bool = False,
    verify_after: bool = True,
    scroll: bool = True,
) -> bool:
    val = str(value or "").strip()
    if not val:
        return False
    if verify_after and not skip_existing_check:
        existing = read_attribute_from_dom(driver, container_id, "tag")
        if any(_norm_attr_text(val) == _norm_attr_text(a) for a in existing):
            return True
    attribute_input = _locate_attribute_input(
        driver, wait, container_id, input_id, scroll=scroll
    )
    if not attribute_input:
        return False
    try:
        attribute_input.click()
        attribute_input.send_keys(val)
        time.sleep(short_sleep)
        attribute_input.send_keys(Keys.ENTER)
        time.sleep(short_sleep)
        if not verify_after or skip_existing_check:
            return True
        actual = read_attribute_from_dom(driver, container_id, "tag")
        return any(_norm_attr_text(val) == _norm_attr_text(a) for a in actual)
    except Exception:
        return False


_PLACEHOLDER_DENY = frozenset({
    "a", "1", "请输入", "请选择", "请输入或者选择",
    "please enter", "please select", "无",
})


def _is_placeholder_value(text: str) -> bool:
    s = str(text or "").strip().lower()
    if not s:
        return True
    if s in {x.lower() for x in _PLACEHOLDER_DENY}:
        return True
    return any(p in s for p in ("请输入", "请选择", "please enter", "please select"))


def _scrape_attribute_options_from_page(driver, container_id: str, select_type: str) -> List[str]:
    """配置无值池时，从页面下拉/标签区刮取可选项（排除 placeholder）。"""
    cid = str(container_id or "").strip()
    if not cid:
        return []
    options: List[str] = []
    try:
        container = driver.find_element(By.ID, cid)
        if select_type == "tag":
            for el in container.find_elements(By.CSS_SELECTOR, ".next-tag .next-tag-body, .next-tag-inner"):
                text = str(el.text or "").strip()
                if text and not _is_placeholder_value(text) and text not in options:
                    options.append(text)
        for el in container.find_elements(By.CSS_SELECTOR, ".next-menu-item, [role='option'], .next-select-menu-item"):
            text = str(el.text or "").strip()
            if text and not _is_placeholder_value(text) and text not in options:
                options.append(text)
    except Exception:
        return []
    return options


def snapshot_all_attribute_values(
    driver,
    attr_config: AttributeConfig,
) -> Dict[str, List[str]]:
    """验收用：批量读取页面上各属性当前值（原值 / 填后值）。"""
    read_specs: List[Dict[str, str]] = []
    name_by_cid: Dict[str, str] = {}
    type_by_cid: Dict[str, str] = {}
    for attr_name, item in attr_config.all_attributes.items():
        if _is_skipped_attr(attr_name, attr_config):
            continue
        cid = str(item.container_id or "").strip()
        if not cid or not _container_exists(driver, cid):
            continue
        stype = str(item.select_type or "")
        read_specs.append({"cid": cid, "type": stype})
        name_by_cid[cid] = attr_name
        type_by_cid[cid] = stype

    out: Dict[str, List[str]] = {}
    batch = read_attributes_batch_from_dom(driver, read_specs)
    for cid, attr_name in name_by_cid.items():
        actual = batch.get(cid)
        if actual is None or (not actual and cid not in batch):
            actual = _read_attribute_actual(driver, cid, type_by_cid.get(cid, ""))
        out[attr_name] = list(actual or [])
    return out


def build_acceptance_attribute_audit(
    attr_config: AttributeConfig,
    original: Dict[str, List[str]],
    planned: Dict[str, List[str]],
    final: Dict[str, List[str]],
) -> List[Dict[str, Any]]:
    """验收用：汇总每个属性的原值、设定值、填后值。"""
    rows: List[Dict[str, Any]] = []
    names: List[str] = []
    for attr_name in attr_config.all_attributes:
        if _is_skipped_attr(attr_name, attr_config):
            continue
        if attr_name not in names:
            names.append(attr_name)
    for attr_name in planned:
        if attr_name not in names:
            names.append(attr_name)
    for attr_name in original:
        if attr_name not in names:
            names.append(attr_name)

    for attr_name in names:
        item = attr_config.all_attributes.get(attr_name)
        if not item or _is_skipped_attr(attr_name, attr_config):
            continue
        orig = list(original.get(attr_name) or [])
        plan = list(planned.get(attr_name) or [])
        fin = list(final.get(attr_name) or [])
        if not orig and not plan and not fin:
            continue
        match = None
        if plan:
            match = _values_match(fin, plan)
        rows.append({
            "attr_name": attr_name,
            "select_type": str(item.select_type or ""),
            "required": str(item.type or "") == "required",
            "original_values": orig,
            "planned_values": plan,
            "final_values": fin,
            "match": match,
        })
    return rows


def _fill_all_attributes(
    driver,
    attr_config: AttributeConfig,
    pre_generated_values: Optional[Dict] = None,
    fill_report: Optional[List[Dict[str, Any]]] = None,
    acceptance_audit: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, List[str]]:
    _expand_attribute_sections(driver)
    _hide_attribute_balloons_once(driver)
    all_containers = _collect_all_attribute_containers(driver)
    visible = _collect_visible_attribute_containers(driver)
    scan_ids = all_containers or visible
    logger.info(f"页面属性区块: 可见 {len(visible)} 个，总计 {len(scan_ids)} 个")

    track_acceptance = acceptance_audit is not None or fill_report is not None
    original_snap: Dict[str, List[str]] = {}
    if track_acceptance:
        original_snap = snapshot_all_attribute_values(driver, attr_config)
        logger.info(f"[验收快照] 属性原值 {len(original_snap)} 项")

    logger.info("属性填写：按字段处理（无批量清空，仅移除与目标不一致的原值）")

    planned: Dict[str, List[str]] = {}
    ordered: List[tuple] = []
    for attr_name, item in attr_config.all_attributes.items():
        if _is_skipped_attr(attr_name, attr_config):
            continue
        priority = 0 if str(item.type or "") == "required" else 1
        ordered.append((priority, attr_name, item))
    ordered.sort(key=lambda x: (x[0], x[1]))

    for _, attr_name, item in ordered:
        cid = str(item.container_id or "").strip()
        is_required = str(item.type or "") == "required"
        select_type = str(item.select_type or "")
        if cid and cid not in scan_ids and not _container_exists(driver, cid):
            logger.debug(f"{attr_name}: 页面无 {cid}，跳过")
            _append_attr_fill_record(
                fill_report,
                attr_name=attr_name,
                select_type=select_type,
                required=is_required,
                phase="first_pass",
                values=[],
                duration_s=0.0,
                status="skipped_no_container",
                verify="n/a",
            )
            continue
        actual_values = pre_generated_values.get(attr_name) if pre_generated_values else None
        expected_preview = _expected_values_for_attr(
            attr_config, attr_name, item, pre_generated_values
        )
        t_attr = time.perf_counter()
        status = "filled"
        error_msg = ""
        intended: List[str] = []
        try:
            intended = _fill_single_attribute(
                driver,
                attr_name,
                item,
                attr_config,
                actual_values,
                verify_after=False,
                scroll_to_field=True,
            )
            if intended:
                planned[attr_name] = intended
            elif (
                expected_preview
                and cid
                and _verify_attribute_values(
                    driver, cid, select_type, expected_preview
                )
            ):
                planned[attr_name] = expected_preview
                status = "already_ok"
            elif expected_preview:
                planned[attr_name] = expected_preview
                status = "partial"
            else:
                status = "empty"
        except Exception as e:
            status = "error"
            error_msg = str(e)
            logger.error(f"填写属性 {attr_name} 失败: {e}")
        _append_attr_fill_record(
            fill_report,
            attr_name=attr_name,
            select_type=select_type,
            required=is_required,
            phase="first_pass",
            values=intended or expected_preview,
            duration_s=time.perf_counter() - t_attr,
            status=status,
            error=error_msg,
            original=original_snap.get(attr_name),
            planned=intended or expected_preview,
        )

    time.sleep(0.5)
    _verify_and_refill_once(driver, attr_config, planned, fill_report=fill_report)

    if acceptance_audit is not None:
        final_snap = snapshot_all_attribute_values(driver, attr_config)
        audit_rows = build_acceptance_attribute_audit(
            attr_config, original_snap, planned, final_snap
        )
        acceptance_audit.clear()
        acceptance_audit.extend(audit_rows)
        logger.info(f"[验收快照] 属性填后值 {len(final_snap)} 项，审计 {len(audit_rows)} 条")

    return planned


def _list_mismatched_attributes(
    driver,
    attr_config: AttributeConfig,
    planned: Dict[str, List[str]],
) -> List[tuple]:
    """批量对比计划值与页面实际值，返回 [(attr_name, expected), ...]。"""
    mismatched: List[tuple] = []
    for attr_name, expected in (planned or {}).items():
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue
        cid = str(item.container_id or "").strip()
        if not cid:
            continue
        select_type = str(item.select_type or "")
        actual = _read_attribute_actual(driver, cid, select_type)
        if not _values_match(actual, expected) and not (
            select_type == "single_search"
            and all(_single_search_value_matched(actual, v) for v in expected)
        ):
            mismatched.append((attr_name, expected))
    return mismatched


def _read_planned_actual(
    driver,
    attr_config: AttributeConfig,
    attr_name: str,
    expected: List[str],
) -> List[str]:
    item = attr_config.all_attributes.get(attr_name)
    if not item:
        return []
    cid = str(item.container_id or "").strip()
    if not cid:
        return []
    select_type = str(item.select_type or "")
    actual = _read_attribute_actual(driver, cid, select_type)
    if select_type == "single_search":
        if all(_single_search_value_matched(actual, v) for v in expected):
            return actual
    return actual


def _verify_and_refill_once(
    driver,
    attr_config: AttributeConfig,
    planned: Dict[str, List[str]],
    fill_report: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """全部填完后统一验收；不一致或未填的字段仅重填一次。"""
    t_verify = time.perf_counter()
    mismatched = _list_mismatched_attributes(driver, attr_config, planned)
    mismatch_names = {name for name, _ in mismatched}

    for attr_name, expected in (planned or {}).items():
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue
        actual = _read_planned_actual(driver, attr_config, attr_name, expected)
        ok = attr_name not in mismatch_names
        _set_attr_verify_on_report(
            fill_report, attr_name, "ok" if ok else "mismatch", actual=actual, phase="first_pass"
        )

    verify_duration = time.perf_counter() - t_verify
    if fill_report is not None:
        _append_attr_fill_record(
            fill_report,
            attr_name="(批量验收)",
            select_type="",
            required=False,
            phase="batch_verify",
            values=[],
            duration_s=verify_duration,
            status="ok" if not mismatched else "mismatch",
            verify="ok" if not mismatched else "mismatch",
        )

    if not mismatched:
        logger.info(f"[属性验收] 首轮全部通过（{len(planned)} 项）")
        return

    names = [name for name, _ in mismatched]
    logger.warning(f"[属性验收] {len(mismatched)} 项未落盘，重填一次: {names}")
    for attr_name, expected in mismatched:
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue
        cid = str(item.container_id or "").strip()
        select_type = str(item.select_type or "")
        if cid and _verify_attribute_values(driver, cid, select_type, expected):
            logger.info(f"{attr_name} 复查已落盘，跳过重填")
            continue
        if cid:
            _scroll_attribute_container(driver, cid)
        t_refill = time.perf_counter()
        status = "filled"
        error_msg = ""
        try:
            _fill_single_attribute(
                driver,
                attr_name,
                item,
                attr_config,
                expected,
                verify_after=False,
                scroll_to_field=True,
            )
        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            logger.error(f"{attr_name} 重填异常: {exc}")
        _append_attr_fill_record(
            fill_report,
            attr_name=attr_name,
            select_type=str(item.select_type or ""),
            required=str(item.type or "") == "required",
            phase="refill",
            values=expected,
            duration_s=time.perf_counter() - t_refill,
            status=status,
            verify="pending",
            error=error_msg,
        )

    still_bad = _list_mismatched_attributes(driver, attr_config, planned)
    still_names = {name for name, _ in still_bad}
    for attr_name, expected in (planned or {}).items():
        if attr_name not in mismatch_names:
            continue
        actual = _read_planned_actual(driver, attr_config, attr_name, expected)
        ok = attr_name not in still_names
        _set_attr_verify_on_report(
            fill_report, attr_name, "ok" if ok else "mismatch", actual=actual, phase="refill"
        )

    if still_bad:
        still_list = [name for name, _ in still_bad]
        logger.error(f"[属性验收] 重填后仍有 {len(still_bad)} 项未落盘: {still_list}")
    else:
        logger.info(f"[属性验收] 重填后全部通过（{len(planned)} 项）")


def _expected_values_for_attr(
    attr_config: AttributeConfig,
    attr_name: str,
    item: AttributeItemConfig,
    pre_generated_values: Optional[Dict],
) -> List[str]:
    pool = [str(v).strip() for v in (item.values or []) if str(v).strip()]
    actual_values = (pre_generated_values or {}).get(attr_name)
    picked = _pick_fill_values(attr_config, attr_name, item.values or [], actual_values)
    return [v for v in picked if str(v).strip()]


def _fill_single_attribute(
    driver,
    attr_name: str,
    item: AttributeItemConfig,
    attr_config: AttributeConfig,
    actual_values: Optional[List[str]] = None,
    verify_after: bool = True,
    scroll_to_field: bool = True,
) -> List[str]:
    is_required = str(item.type or "") == "required"
    WAIT_TIME, SHORT_SLEEP, NORMAL_SLEEP = _attribute_timing(attr_config, is_required)
    container_id = item.container_id
    if container_id and not _container_exists(driver, container_id):
        logger.debug(f"{attr_name}: 页面无容器 {container_id}，跳过")
        return []
    original_values = item.values
    input_id = item.input_id
    select_type = item.select_type
    wait = WebDriverWait(driver, WAIT_TIME)

    pool = [str(v).strip() for v in (original_values or []) if str(v).strip()]
    expected_n = _resolve_fill_count(attr_config, attr_name, pool)
    values = _pick_fill_values(attr_config, attr_name, original_values or [], actual_values)

    valid_values = [v for v in values if str(v).strip()]
    if not valid_values:
        if not pool:
            logger.warning(f"{attr_name}：配置无值池，跳过填写")
            return []
        scraped = _scrape_attribute_options_from_page(driver, container_id, select_type)
        scraped = [v for v in scraped if not _is_placeholder_value(v)]
        if scraped:
            valid_values = scraped[: max(1, expected_n)]
            logger.info(f"{attr_name}：已从页面读取选项 → {valid_values}")
        else:
            logger.warning(f"{attr_name}：无有效值且页面无可选项，跳过填写")
            return []

    if scroll_to_field:
        _scroll_attribute_container(driver, container_id)

    to_fill_preview, skip_field = _prepare_field_before_fill(
        driver, wait, container_id, input_id, select_type, valid_values, SHORT_SLEEP,
    )
    if skip_field:
        logger.info(f"{attr_name} 已是目标值，跳过")
        return valid_values

    input_selector = (
        f"#{container_id} input#{input_id}"
        if input_id
        else f"#{container_id} .sell-catProp-struct .next-input input"
    )

    logger.info(
        f"填写【{attr_name}】目标={valid_values} 待填={to_fill_preview or valid_values}"
    )

    ok = False
    if select_type == "input":
        ok = _fill_input_reliable(
            driver, wait, container_id, input_id, valid_values, input_selector,
            False, SHORT_SLEEP, NORMAL_SLEEP,
            verify_after=verify_after, scroll_to_field=scroll_to_field,
        )
    elif select_type == "tag":
        ok = _fill_tag_reliable(
            driver, wait, container_id, input_id, valid_values,
            False, SHORT_SLEEP, NORMAL_SLEEP,
            verify_after=verify_after, scroll_to_field=scroll_to_field,
        )
    elif select_type == "single_search":
        ok = _fill_single_search_reliable(
            driver, wait, container_id, input_id, valid_values, input_selector,
            False, SHORT_SLEEP, NORMAL_SLEEP,
            verify_after=verify_after, scroll_to_field=scroll_to_field,
        )

    if select_type in ("input", "tag", "single_search"):
        if not verify_after:
            if ok:
                logger.info(f"{attr_name} 填写完成")
                return valid_values
            logger.warning(f"{attr_name} 填写未完全落盘")
            return []
        if _verify_attribute_values(
            driver, container_id, select_type, valid_values
        ):
            logger.info(f"{attr_name} 填写完成")
            return valid_values
        if ok:
            if is_required:
                time.sleep(SHORT_SLEEP)
            logger.info(f"{attr_name} 填写完成")
            return valid_values
        logger.warning(f"{attr_name} 填写未通过落盘验收")
        return []

    attribute_input = _locate_attribute_input(
        driver, wait, container_id, input_id, scroll=scroll_to_field
    )
    if not attribute_input:
        logger.warning(f"无法定位{attr_name}输入框，跳过")
        return []

    to_fill, skip_field = _prepare_field_before_fill(
        driver, wait, container_id, input_id, select_type, valid_values, SHORT_SLEEP,
    )
    if skip_field:
        return valid_values

    for idx, value in enumerate(to_fill or valid_values):
        try:
            if select_type == "auto_complete":
                if _fill_autocomplete_js(driver, container_id, input_id, value):
                    time.sleep(SHORT_SLEEP)
                    if _wait_one_value_committed(
                        driver, container_id, select_type, value, timeout=1.0
                    ):
                        continue

            attribute_input = (
                _locate_attribute_input(
                    driver, wait, container_id, input_id, scroll=scroll_to_field
                )
                or attribute_input
            )
            if not attribute_input:
                continue
            attribute_input.click()
            time.sleep(SHORT_SLEEP)

            if attr_name in ["原产地", "产品类型"]:
                driver.execute_script(
                    """
                    const inp = arguments[0];
                    inp.focus();
                    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                    setter.call(inp, '');
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                    """,
                    attribute_input,
                )
                attribute_input.send_keys(value)
            else:
                attribute_input.send_keys(value)

            time.sleep(NORMAL_SLEEP)

            if select_type == "auto_complete":
                if not _select_dropdown_option(
                    driver, wait, attr_name, value, select_type, timeout=0.6
                ):
                    attribute_input.send_keys(Keys.ENTER)
                time.sleep(SHORT_SLEEP)

        except StaleElementReferenceException:
            time.sleep(0.15)
        except Exception as e:
            logger.warning(f"{attr_name} 填写值 '{value}' 失败: {e}")

    if not verify_after:
        logger.info(f"{attr_name} 填写完成")
        return valid_values
    if _verify_attribute_values(driver, container_id, select_type, valid_values):
        logger.info(f"{attr_name} 填写完成")
        return valid_values
    logger.warning(f"{attr_name} 填写未通过落盘验收")
    return []


def read_attributes_batch_from_dom(
    driver,
    specs: List[Dict[str, str]],
) -> Dict[str, List[str]]:
    """一次 JS 批量读取多个属性容器当前值（验收加速）。"""
    if not specs:
        return {}
    try:
        raw = driver.execute_script(
            """
            const specs = arguments[0];
            const out = {};
            const deny = (t) => {
              const s = (t || '').trim().toLowerCase();
              if (!s || s === 'a' || s === '1') return true;
              return s.includes('请输入') || s.includes('请选择');
            };
            const norm = (s) => (t => (t || '').trim())(s);
            for (const spec of specs) {
              const cid = spec.cid;
              const type = spec.type || '';
              const root = document.getElementById(cid);
              if (!root) { out[cid] = []; continue; }
              const tags = [];
              const seen = new Set();
              const pushTag = (t) => {
                const text = norm(t);
                if (!text || deny(text)) return;
                const key = text.toLowerCase();
                if (!seen.has(key)) { seen.add(key); tags.push(text); }
              };
              for (const el of root.querySelectorAll('.next-tag .next-tag-body, .next-tag-inner')) {
                pushTag(el.innerText || el.textContent);
              }
              if (type === 'tag') {
                out[cid] = tags;
                continue;
              }
              if (type === 'single_search' && tags.length) {
                out[cid] = tags;
                continue;
              }
              const values = [];
              for (const inp of root.querySelectorAll('input')) {
                const val = norm(inp.value);
                if (val && !deny(val) && !values.includes(val)) values.push(val);
              }
              if (type === 'input') {
                if (values.length === 1 && values[0].includes(',')) {
                  out[cid] = values[0].replace(/，/g, ',').split(',').map(s => s.trim()).filter(Boolean);
                } else {
                  out[cid] = values;
                }
                continue;
              }
              out[cid] = tags.length ? tags : values;
            }
            return out;
            """,
            specs,
        )
        return {str(k): list(v or []) for k, v in (raw or {}).items()}
    except Exception:
        return {}


def read_attribute_from_dom(driver, container_id: str, select_type: str) -> List[str]:
    """从页面读取属性当前值（供验收对比）。"""
    cid = str(container_id or "").strip()
    if not cid:
        return []
    try:
        container = driver.find_element(By.ID, cid)
    except Exception:
        return []
    if select_type == "tag":
        tags: List[str] = []
        seen: set = set()
        for el in container.find_elements(
            By.CSS_SELECTOR, ".next-tag .next-tag-body, .next-tag-inner"
        ):
            text = str(el.text or "").strip()
            key = _norm_attr_text(text)
            if text and not _is_placeholder_value(text) and key not in seen:
                seen.add(key)
                tags.append(text)
        return tags
    if select_type == "input":
        for inp in container.find_elements(By.CSS_SELECTOR, "input"):
            val = str(inp.get_attribute("value") or "").strip()
            if val and not _is_placeholder_value(val):
                return [v.strip() for v in val.replace("，", ",").split(",") if v.strip()]
        return []
    if select_type == "single_search":
        tags: List[str] = []
        for el in container.find_elements(
            By.CSS_SELECTOR, ".next-tag .next-tag-body, .next-tag-inner"
        ):
            text = str(el.text or "").strip()
            if text and text not in tags:
                tags.append(text)
        if tags:
            return tags
    values: List[str] = []
    for inp in container.find_elements(By.CSS_SELECTOR, "input"):
        val = str(inp.get_attribute("value") or "").strip()
        if val and val not in values:
            values.append(val)
    return values


def verify_filled_attributes(
    driver,
    attr_config: AttributeConfig,
    planned: Optional[Dict[str, List[str]]] = None,
) -> List[str]:
    """对比计划填入与页面实际值，返回问题列表。"""
    issues: List[str] = []
    planned = planned or {}

    read_specs: List[Dict[str, str]] = []
    attr_by_cid: Dict[str, str] = {}
    check_items: Dict[str, List[str]] = dict(planned)
    for attr_name, item in attr_config.all_attributes.items():
        if _is_skipped_attr(attr_name, attr_config):
            continue
        if str(item.type or "") != "required":
            continue
        if attr_name in check_items:
            continue
        cid = str(item.container_id or "").strip()
        if not cid or not _container_exists(driver, cid):
            issues.append(f"属性/{attr_name}: 必填项未填写（页面无容器或首轮跳过）")
            continue
        actual = _read_attribute_actual(driver, cid, str(item.select_type or ""))
        if not actual:
            issues.append(f"属性/{attr_name}: 必填项未填写")

    if not check_items:
        return issues

    for attr_name, expected in check_items.items():
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue
        cid = str(item.container_id or "").strip()
        if not cid:
            continue
        read_specs.append({"cid": cid, "type": str(item.select_type or "")})
        attr_by_cid[cid] = attr_name

    batch = read_attributes_batch_from_dom(driver, read_specs)
    ok_count = 0

    for attr_name, expected in check_items.items():
        item = attr_config.all_attributes.get(attr_name)
        if not item:
            continue
        cid = str(item.container_id or "").strip()
        actual = batch.get(cid) if cid else []
        if actual is None or (not actual and cid not in batch):
            actual = read_attribute_from_dom(driver, cid, str(item.select_type or ""))
        if any(str(v).strip().lower() == "a" for v in actual):
            issues.append(f"属性/{attr_name}: 页面含占位符 a，实际={actual}")
            continue
        if _values_match(actual, expected):
            ok_count += 1
            continue
        missing = [
            v for v in expected
            if not any(_norm_attr_text(v) == _norm_attr_text(a) for a in actual)
        ]
        extra = [
            a for a in actual
            if not any(_norm_attr_text(a) == _norm_attr_text(v) for v in expected)
        ]
        if missing or extra:
            issues.append(
                f"属性/{attr_name}: 缺少 {missing} 多余 {extra}，期望={expected} 实际={actual}"
            )

    total = len(check_items)
    if ok_count == total and not issues:
        logger.info(f"[验收OK] 属性 {ok_count}/{total} 全部通过")
    else:
        logger.info(f"[验收] 属性 {ok_count}/{total} 通过，问题 {len(issues)} 条")
    return issues


def _select_dropdown_option(
    driver,
    wait,
    attr_name: str,
    value: str,
    select_type: str,
    timeout: Optional[float] = None,
) -> bool:
    try:
        if select_type == "tag":
            return True

        effective_wait = WebDriverWait(driver, timeout) if timeout is not None else wait

        if select_type == "auto_complete":
            target_xpath = f"//div[contains(@class, 'next-auto-complete-option') and contains(text(), '{value}')]"
            target = effective_wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            driver.execute_script("arguments[0].click();", target)
            return True

        if select_type == "single_search":
            dropdown_sel = (
                ".next-overlay-wrapper.opened .sell-o-select-options, "
                ".next-overlay-wrapper.opened .next-select-menu"
            )
            target_xpath = (
                f"//li[contains(text(), '{value}') and "
                f"(contains(@class, 'next-menu-item') or contains(@class, 'options-item'))]"
            )
            effective_wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, dropdown_sel)))
            try:
                target = effective_wait.until(EC.element_to_be_clickable((By.XPATH, target_xpath)))
            except Exception:
                target = effective_wait.until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, f"{dropdown_sel} li:first-child"))
                )
            driver.execute_script("arguments[0].click();", target)
            return True

        return False
    except TimeoutException:
        return False
    except Exception:
        return False
