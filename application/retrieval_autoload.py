# application/retrieval_autoload.py
# Single-file: auto-ingest everything under data/knowledge + minimal TF-IDF retriever.
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import json, time, re, math

# ---------------- Config ----------------
# KNOW_ROOT = Path("FitU/data/knowledge")
KNOW_ROOT = Path(__file__).parent.parent / "data" / "knowledge"
KNOW_ROOT = KNOW_ROOT.resolve()  # 转换为绝对路径
STATE_PATH = KNOW_ROOT / ".ingest_state.json"   # 保存指纹、清单、时间戳
INDEX_JSONL = KNOW_ROOT / "index.jsonl"         # 索引：逐分块一行
IDF_JSON = KNOW_ROOT / "idf.json"               # idf 统计
# 可自行扩展；注意全部按小写后比较
EXTS = {".md", ".markdown", ".txt", ".pdf", ".csv", ".tsv", ".docx"}

# ----------------- 读取器（多格式，尽量不额外依赖） -----------------
def _read_text_file(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return p.read_text(encoding="latin-1", errors="ignore")

def _read_pdf(p: Path) -> str:
    try:
        from PyPDF2 import PdfReader  # 可选：pip install PyPDF2
        reader = PdfReader(str(p))
        return "\n".join([(page.extract_text() or "") for page in reader.pages])
    except Exception:
        return f"[PDF not parsed: install PyPDF2] {p.name}"

def _read_docx(p: Path) -> str:
    try:
        import docx  # 可选：pip install python-docx
        doc = docx.Document(str(p))
        return "\n".join([para.text for para in doc.paragraphs])
    except Exception:
        return f"[DOCX not parsed: install python-docx] {p.name}"

def _read_csv_tsv(p: Path) -> str:
    # 简化：整文件当作文本；无需 pandas 依赖
    return _read_text_file(p)

def _load_file(p: Path) -> str:
    suf = p.suffix.lower()
    if suf in {".md", ".markdown", ".txt"}:  return _read_text_file(p)
    if suf in {".csv", ".tsv"}:              return _read_csv_tsv(p)
    if suf == ".pdf":                         return _read_pdf(p)
    if suf == ".docx":                        return _read_docx(p)
    return _read_text_file(p)

# ----------------- 轻量分词/分块/向量 -----------------
_tok_re = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fff\-/]+")

def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in _tok_re.findall(s)]

def _split_chunks(text: str, max_tokens: int = 220) -> List[Tuple[List[str], str]]:
    """
    返回 [(token_list, raw_snippet), ...]
    - token_list 用于检索
    - raw_snippet 用于人类可读摘要（折叠多空白，截断）
    """
    def _mk_snip(src: str, limit: int = 220) -> str:
        s = re.sub(r"\s+", " ", src).strip()
        return s[:limit]

    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks: List[Tuple[List[str], str]] = []
    for para in paras:
        toks = _tokenize(para)
        if not toks:
            continue
        for i in range(0, len(toks), max_tokens):
            piece = toks[i:i+max_tokens]
            if piece:
                raw_piece = " ".join(para.split())  # 同段原文压空白
                chunks.append((piece, _mk_snip(raw_piece)))
    if not chunks and text.strip():
        toks = _tokenize(text)
        for i in range(0, len(toks), max_tokens):
            piece = toks[i:i+max_tokens]
            if piece:
                chunks.append((piece, _mk_snip(text)))
    return chunks

def _tf_count(tokens: List[str]) -> Dict[str, int]:
    d: Dict[str, int] = {}
    for t in tokens:
        d[t] = d.get(t, 0) + 1
    return d

# ----------------- 单文件版 TF-IDF 检索器 -----------------
class SimpleTfidfRetriever:
    """
    - ingest(paths, rebuild_index=True): 扫描文件->分块->写 index.jsonl + idf.json
    - search(query, k): 返回最相关的分块（含 path, score, snippet）
    索引规模中小型足够；将来可无缝替换为向量库。
    """
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.idf: Dict[str, float] = {}
        self.N: int = 0
        if IDF_JSON.exists():
            try:
                obj = json.loads(IDF_JSON.read_text(encoding="utf-8"))
                self.idf = obj.get("idf", {})
                self.N = int(obj.get("N", 0))
            except Exception:
                self.idf, self.N = {}, 0

    def ingest(self, paths: List[str], rebuild_index: bool = True) -> int:
        docs: List[Dict] = []
        df: Dict[str, int] = {}
        n_chunks = 0

        for sp in paths:
            p = Path(sp)
            if not p.exists() or not p.is_file():
                continue
            if p.suffix.lower() not in EXTS:
                continue

            raw = _load_file(p)
            if not raw.strip():
                continue

            for ci, (toks, snippet) in enumerate(_split_chunks(raw, max_tokens=220)):
                if not toks:
                    continue
                tf = _tf_count(toks)
                # df 统计（按出现过该词的分块计数）
                for term in tf.keys():
                    df[term] = df.get(term, 0) + 1

                docs.append({
                    "path": str(p),
                    "chunk_id": ci,
                    "text_snippet": snippet,
                    "tf": tf
                })
                n_chunks += 1

        # 写 index.jsonl
        INDEX_JSONL.parent.mkdir(parents=True, exist_ok=True)
        with INDEX_JSONL.open("w", encoding="utf-8") as f:
            for rec in docs:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 写 idf.json
        N = max(n_chunks, 1)
        idf = {t: math.log((N + 1.0) / (df_t + 1.0)) + 1.0 for t, df_t in df.items()}
        IDF_JSON.write_text(json.dumps({"idf": idf, "N": N}, ensure_ascii=False), encoding="utf-8")

        self.idf, self.N = idf, N
        return n_chunks

    def _iter_docs(self):
        if not INDEX_JSONL.exists():
            return
        with INDEX_JSONL.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    yield json.loads(line)
                except Exception:
                    continue

    def search(self, query: str, k: int = 5) -> List[Dict]:
        q_toks = _tokenize(query)
        if not q_toks or not self.idf:
            return []
        # query tf-idf
        q_tf = _tf_count(q_toks)
        q_vec: Dict[str, float] = {}
        for t, c in q_tf.items():
            idf = self.idf.get(t, 0.0)
            if idf > 0.0:
                q_vec[t] = (1.0 + math.log(1.0 + c)) * idf
        q_norm = math.sqrt(sum(v*v for v in q_vec.values())) or 1.0

        # 计算每个文档分块相似度
        scored: List[Tuple[float, Dict]] = []
        for rec in self._iter_docs() or []:
            tf = rec.get("tf", {})
            dot = 0.0
            d_norm_sq = 0.0
            for t, c in tf.items():
                idf = self.idf.get(t, 0.0)
                if idf <= 0.0:
                    continue
                w = (1.0 + math.log(1.0 + c)) * idf
                d_norm_sq += w*w
                if t in q_vec:
                    dot += q_vec[t] * w
            d_norm = math.sqrt(d_norm_sq) or 1.0
            score = dot / (q_norm * d_norm)
            if score > 0.0:
                scored.append((score, rec))

        scored.sort(key=lambda x: x[0], reverse=True)
        out = []
        for s, r in scored[:k]:
            out.append({
                "path": r.get("path"),
                "chunk_id": r.get("chunk_id"),
                "score": round(float(s), 4),
                "snippet": r.get("text_snippet", "")[:240]
            })
        return out

# ----------------- 目录变化检测（与 UI 对接） -----------------
# def _list_files(root: Path) -> List[Path]:
#     files: List[Path] = []
#     if not root.exists():
#         return files
#     ignore_abs = {STATE_PATH.resolve(), INDEX_JSONL.resolve(), IDF_JSON.resolve()}
#     for p in root.rglob("*"):
#         if not p.is_file():
#             continue
#         if p.name.startswith("."):
#             continue
#         if p.resolve() in ignore_abs:
#             continue
#         if p.suffix.lower() not in EXTS:
#             continue
#         files.append(p)
#     return files
# application/retrieval_autoload.py
# application/retrieval_autoload.py
def _list_files(root: Path) -> List[Path]:
    """修复路径解析+简化查找，确保找到文件"""
    # 强制转换为绝对路径，处理含空格的路径
    root_abs = root.resolve()
    print(f"=== 查找知识库文件 ===")
    print(f"目标文件夹绝对路径：{root_abs}")

    # 简化：先查找根目录下的支持文件（不递归，避免子文件夹问题）
    supported_ext = {".md", ".txt"}  # 只保留简单格式（优先确保能找到）
    files = []

    # 直接遍历根目录下的文件（不递归，减少复杂度）
    for file in root_abs.iterdir():
        if file.is_file() and file.suffix in supported_ext:
            files.append(file)
            print(f"找到文件：{file.name}（路径：{file}）")

    # 打印查找结果
    print(f"最终找到支持的文件数量：{len(files)}")
    if not files:
        print("⚠️  未找到任何知识库文件！请检查：")
        print(f"1. 文件夹 {root_abs} 下是否有 .md 或 .txt 文件；")
        print(f"2. 文件是否直接放在该文件夹下（暂不支持子文件夹）；")
        print(f"3. 文件后缀是否为小写（如 .MD 需改为 .md）。")

    return files
def _fingerprint(p: Path) -> Tuple[int, int]:
    st = p.stat()
    return (int(st.st_size), int(getattr(st, "st_mtime_ns", int(st.st_mtime))))

def _load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    # 初始状态
    return {
        "files": {},               # {rel: {"size": int, "mtime": int}}
        "fingerprint": "",         # md5 over (rel|size|mtime)
        "last_build_ts": 0.0,      # 上次真正构建索引的时间
        "last_scan_ts": 0.0        # 上次扫描完成的时间
    }

def _save_state(state: Dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

def _build_manifest(files: List[Path]) -> Dict[str, Dict[str, int]]:
    manifest: Dict[str, Dict[str, int]] = {}
    for p in files:
        rel = str(p.relative_to(KNOW_ROOT))
        size, mtime = _fingerprint(p)
        manifest[rel] = {"size": size, "mtime": mtime}
    return manifest

def _diff(old: Dict[str, Dict[str,int]], new: Dict[str, Dict[str,int]]):
    old_keys, new_keys = set(old), set(new)
    added = sorted(list(new_keys - old_keys))
    removed = sorted(list(old_keys - new_keys))
    changed = []
    for k in (old_keys & new_keys):
        if old[k] != new[k]:
            changed.append(k)
    return added, removed, changed

def _fingerprint_manifest(m: Dict[str, Dict[str, int]]) -> str:
    import hashlib
    h = hashlib.md5()
    for k in sorted(m.keys()):
        v = m[k]
        h.update(f"{k}|{v['size']}|{v['mtime']}".encode("utf-8"))
    return h.hexdigest()

@dataclass
class KnowledgeStatus:
    n_files: int = 0
    added: int = 0
    removed: int = 0
    changed: int = 0
    rebuilt: bool = False
    last_scan_ts: float = 0.0

# ---- 单例式自动加载器 ----
_autoloader: Optional["KnowledgeAutoLoader"] = None


class KnowledgeAutoLoader:

    def __init__(self):
        # 使用已定义的 KNOW_ROOT 而不是重新定义
        self.root = KNOW_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        self.retriever = _init_retriever()
        self.status: KnowledgeStatus = KnowledgeStatus()

    def maybe_update_index(self, *, force_rebuild: bool = False,
                           autobuild: bool = True, cooldown_sec: int = 3) -> KnowledgeStatus:
        files = _list_files(self.root)
        if not files:
            self.status = KnowledgeStatus(n_files=0, added=0, removed=0, changed=0, rebuilt=False)
            return self.status

        manifest_new = _build_manifest(files)
        state = _load_state()
        curr_fp = _fingerprint_manifest(manifest_new)
        prev_fp = state.get("fingerprint", "")

        # 强制重建或文件变化时，重新加载文件
        do_rebuild = force_rebuild or (curr_fp != prev_fp)
        rebuilt = False

        if do_rebuild:
            print(f"=== 加载文件到检索器 ===")
            path_list = [str(f) for f in files]
            # 适配 SimpleTfidfRetriever 的 ingest 方法（假设其支持传入文件路径列表）
            self.retriever.ingest(path_list)  # 强制重建索引
            print(f"成功加载 {len(path_list)} 个文件到检索器")
            rebuilt = True

        # 保存状态
        state["files"] = manifest_new
        state["fingerprint"] = curr_fp
        state["last_build_ts"] = time.time()
        _save_state(state)

        self.status = KnowledgeStatus(
            n_files=len(files),
            added=len([f for f in files if f.name not in state.get("files", {})]),
            removed=0,
            changed=0,
            rebuilt=rebuilt,
            last_scan_ts=time.time(),
        )
        return self.status


# 确保 _init_retriever 返回 SimpleTfidfRetriever（匹配你的实际使用）
def _init_retriever() -> SimpleTfidfRetriever:  # 明确返回类型
    # from your_retriever_module import SimpleTfidfRetriever  # 替换为你的检索器实际导入路径
    # 初始化空检索器（后续通过 ingest 加载文件）
    return SimpleTfidfRetriever(root=KNOW_ROOT)


# ---- 公共 API（主程序使用这三个） ----
def get_retriever_autoload(autobuild: bool = True, cooldown_sec: int = 15):
    """
    在 App 启动/重跑时调用一次即可：
      - 轻量扫描目录
      - 若检测到变化且过了冷却时间 -> 自动重建
      - 返回检索器（SimpleTfidfRetriever 实例）
    """
    global _autoloader
    if _autoloader is None:
        _autoloader = KnowledgeAutoLoader()
    _autoloader.maybe_update_index(force_rebuild=False, autobuild=autobuild, cooldown_sec=cooldown_sec)
    return _autoloader.retriever

def knowledge_status() -> KnowledgeStatus:
    global _autoloader
    if _autoloader is None:
        _autoloader = KnowledgeAutoLoader()
        _autoloader.maybe_update_index(force_rebuild=False)
    return _autoloader.status

def rescan_and_rebuild() -> KnowledgeStatus:
    global _autoloader
    if _autoloader is None:
        _autoloader = KnowledgeAutoLoader()
    return _autoloader.maybe_update_index(force_rebuild=True)


