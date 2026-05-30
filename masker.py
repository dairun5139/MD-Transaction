"""
MD Transaction — 数据脱敏模块
在对知识源建立向量库之前，自动检测并脱敏文本中的敏感信息。
纯正则实现，无额外依赖。
"""
import re
import sys
from pathlib import Path

# ======================== 脱敏开关配置 ========================
MASK_CONFIG = {
    # 强隐私字段：默认继续脱敏
    "phone": True,
    "id_card": True,
    "credit_code": True,
    "email": True,
    "bank_account": True,
    "ip": False,

    # 业务规则类文档需要保留金额、电价、电量、小时数等关键数字，
    # 否则会影响“结算、限价、保量保价、96点申报”等问答准确性。
    # 如果后续处理的是合同、客户资料、交易流水，可再按需改回 True。
    "amount": False,
    "company_name": False,
    "person_name": False,
    "address": False,
    "price": False,
    "quantity": False,
}

# 绕过脱敏的白名单（保留原样）
WHITELIST = [
    "国家发展改革委",
    "国家能源局",
    "蒙东电力交易中心",
    "国家电网",
    "南方电网",
    "内蒙古电力",
]


# ======================== 第一层：结构化数据 ========================

def _mask_phone(text):
    """手机号 138****5678  |  座机号 0475-****567"""
    # 手机号（含可选分隔符）
    pattern = re.compile(r'(?<!\d)1[3-9]\d[ -]?\d{4}[ -]?\d{4}(?!\d)')
    def _repl(m):
        digits = re.sub(r'\D', '', m.group())
        return digits[:3] + "****" + digits[-4:]
    text = pattern.sub(_repl, text)

    # 座机号（含区号）
    pattern_tel = re.compile(r'(?<!\d)(\d{3,4}[ -]\d{7,8})(?![\d-])')
    def _repl_tel(m):
        parts = re.split(r'[ -]', m.group())
        if len(parts) == 2:
            return parts[0] + "-****" + parts[1][-3:]
        return m.group()
    text = pattern_tel.sub(_repl_tel, text)

    return text


def _mask_id_card(text):
    """身份证号 保留前6后4"""
    pattern = re.compile(
        r'(?<!\d)'
        r'\d{6}'  # 地区码
        r'(?:19|20)\d{2}'  # 年份
        r'(?:0[1-9]|1[0-2])'  # 月份
        r'(?:0[1-9]|[12]\d|3[01])'  # 日
        r'\d{3}'  # 顺序码
        r'[\dXx]'  # 校验码
        r'(?!\d)'
    )
    def _repl(m):
        s = m.group()
        return s[:6] + "********" + s[-4:]
    return pattern.sub(_repl, text)


def _mask_credit_code(text):
    """统一社会信用代码 保留前4后4（排除白名单中的机构）"""
    # 先检查白名单
    for w in WHITELIST:
        if w in text:
            return text

    pattern = re.compile(r'(?<![0-9A-Za-z])([0-9A-HJ-NPQRTUWXY]{18})(?![0-9A-Za-z])')
    def _repl(m):
        s = m.group()
        return s[:4] + "**********" + s[-4:]
    return pattern.sub(_repl, text)


def _mask_email(text):
    """邮箱 a**@company.com"""
    pattern = re.compile(r'([\w.+-]+)@([\w.-]+\.\w{2,})')
    def _repl(m):
        user = m.group(1)
        domain = m.group(2)
        if len(user) > 2:
            masked_user = user[0] + "**" + user[-1]
        else:
            masked_user = user[0] + "***"
        return masked_user + "@" + domain
    return pattern.sub(_repl, text)


def _mask_bank_account(text):
    """银行账号 16-19位数字，保留后4位（需排除身份证/手机号等已被处理的）"""
    pattern = re.compile(r'(?<!\d)(\d{16,19})(?!\d)')
    def _repl(m):
        s = m.group()
        return "****" + s[-4:]
    return pattern.sub(_repl, text)


def _mask_ip(text):
    """IPv4 地址 10.*.*.3"""
    pattern = re.compile(
        r'(?<!\d)'
        r'(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})'
        r'(?!\d)'
    )
    def _repl(m):
        a, b, c, d = m.groups()
        if 0 <= int(a) <= 255 and 0 <= int(b) <= 255 and 0 <= int(c) <= 255 and 0 <= int(d) <= 255:
            return f"{a}.*.*.{d}"
        return m.group()
    return pattern.sub(_repl, text)


def _mask_amount(text):
    """金额：数字 + 元/万元，金额部分替换为 ***"""
    pattern = re.compile(
        r'(?<!\d)'
        r'(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)'
        r'\s*'
        r'(万?元|万?美元|万?欧元)'
        r'(?!\w)'
    )
    def _repl(m):
        unit = m.group(2)
        return f"***{unit}"
    return pattern.sub(_repl, text)


# ======================== 第二层：名称类实体 ========================

_COMPANY_SUFFIX = (
    r'(?:有限责任?公司|股份有限?公司|集团公司?|'
    r'电厂|电站|发电有限公司?|供电公司|电力公司|'
    r'能源有限公司?|新能源有限公司?|'
    r'分公司|子公司|'
    r'风电场|光伏电站|储能电站|'
    r'售电有限公司?|配电有限公司?)'
)


def _mask_company_name(text):
    """公司/机构名称 保留首尾字符，中间脱敏"""
    # 匹配：前导边界 + 名称主体 + 公司后缀
    pattern = re.compile(
        r'(?:^|[，。；、\s（(：:])'
        r'([一-鿿\w]{2,30}?' + _COMPANY_SUFFIX + r')'
        r'(?=[，。；、\s）)：:]|$)',
        re.MULTILINE,
    )
    def _repl(m):
        full = m.group(1)
        # 排除白名单
        for w in WHITELIST:
            if w in full:
                return m.group()
        if len(full) <= 4:
            return m.group()
        return full[0] + "***" + full[-1]
    return pattern.sub(_repl, text)


def _mask_address(text):
    """地址：匹配省/市/县/区/旗/街道/乡/镇/村/路/号/栋 模式"""
    # 详细地址特征：包含区县级 + 街道/路
    pattern = re.compile(
        r'([一-鿿]{2,4}?[省市]'
        r'[一-鿿]{2,6}?[区县旗]'
        r'[一-鿿\d]{2,10}?(?:街道|镇|乡|路|街|村|小区|大院|产业园|开发区)'
        r'(?:[一-鿿\d\-号栋楼幢单元室层号]{2,30})?)'
    )
    def _repl(m):
        s = m.group()
        # 保留省级行政区
        province_end = s.find("省") + 1 if "省" in s else 0
        province_end = max(province_end, 0)
        if province_end > 0:
            return s[:province_end] + "***"
        # 直辖市
        if s[:2] in ("北京", "上海", "天津", "重庆"):
            return s[:2] + "***"
        return s[:2] + "***" + s[-1:]
    return pattern.sub(_repl, text)


def _mask_person_name(text):
    """人名（实验性，默认关闭）"""
    # 常见单姓 + 2-3字名，前后有明确上下文（如：由XX负责、XX先生/女士、XX说等）
    surnames = r'[王李张刘陈杨黄赵周吴徐孙马胡朱郭何罗高林郑梁谢唐许冯宋韩邓彭曹曾田萧潘袁蔡蒋余于杜叶程魏苏吕丁任卢姚沈钟姜崔谭陆范汪廖石金贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔汤温康施文牛]'
    pattern = re.compile(
        rf'(?:(?:由|经|据|与|和|为|对|请|派|委托)(?:{surnames})[一-鿿]{{1,2}})'
        r'|'
        rf'(?:({surnames})[一-鿿]{{1,2}}(?:负责|先生|女士|同志|经理|主任|处长|科长|工程师))'
    )
    return pattern.sub(lambda m: m.group()[0] + "*" * (len(m.group()) - 1), text)


# ======================== 第三层：数值模糊化 ========================

def _mask_price(text):
    """电价：数值 + 元/兆瓦时|元/MWh|元/kWh|厘/kWh，数值模糊为区间标记"""
    pattern = re.compile(
        r'(?<!\d)'
        r'(\d+(?:\.\d{1,4})?)'
        r'\s*'
        r'(元/MWh|元/兆瓦时|元/kWh|元/千瓦时|厘/kWh|厘/千瓦时)'
    )
    def _repl(m):
        try:
            val = float(m.group(1))
            unit = m.group(2)
            # 根据数值大小模糊化为区间
            if val < 1:
                return f"[0-1]{unit}"
            elif val < 10:
                s = str(int(val))
                return f"[{s}-{int(s)+1}]{unit}"
            elif val < 100:
                tens = (int(val) // 10) * 10
                return f"[{tens}-{tens+10}]{unit}"
            elif val < 1000:
                hundreds = (int(val) // 100) * 100
                return f"[{hundreds}-{hundreds+100}]{unit}"
            else:
                thousands = (int(val) // 1000) * 1000
                return f"[{thousands}-{thousands+1000}]{unit}"
        except ValueError:
            return m.group()
    return pattern.sub(_repl, text)


def _mask_quantity(text):
    """电量：数值 + 万千瓦时|万kWh|MWh|MW|万千瓦|万kW，抹去尾数"""
    pattern = re.compile(
        r'(?<!\d)'
        r'(\d+(?:\.\d{1,2})?)'
        r'\s*'
        r'(万千瓦时|万kWh|万kwh|MWh|GWh|MW|GW|万千瓦|万kW|万kw|kW|kw|kWh|kwh)'
        r'(?!\w)'
    )
    def _repl(m):
        try:
            val = float(m.group(1))
            unit = m.group(2)
            if val >= 10000:
                return f"约{val/10000:.0f}万{unit}" if '万' not in unit else f"约{val/10000:.0f}万{unit.replace('万','')}"
            elif val >= 1000:
                return f"约{int(val/1000)*1000}{unit}"
            elif val >= 100:
                return f"约{int(val/100)*100}{unit}"
            elif val >= 10:
                return f"约{int(val/10)*10}{unit}"
            else:
                return f"约{int(val)}{unit}"
        except ValueError:
            return m.group()
    return pattern.sub(_repl, text)


# ======================== 规则注册表 ========================

MASK_RULES = {
    "phone":          _mask_phone,
    "id_card":        _mask_id_card,
    "credit_code":    _mask_credit_code,
    "email":          _mask_email,
    "bank_account":   _mask_bank_account,
    "ip":             _mask_ip,
    "amount":         _mask_amount,
    "company_name":   _mask_company_name,
    "person_name":    _mask_person_name,
    "address":        _mask_address,
    "price":          _mask_price,
    "quantity":       _mask_quantity,
}

# 执行顺序：结构化 → 实体名称 → 数值模糊（后两步依赖前一步的上下文保护）
RULE_ORDER = [
    "phone", "id_card", "credit_code", "email", "bank_account", "ip",
    "amount",  # 在 company_name 之前，避免公司名含数字被误伤
    "company_name", "address", "person_name",
    "price", "quantity",
]


# ======================== 主接口 ========================

def mask_text(text, config=None):
    """对单段文本应用所有启用的脱敏规则。"""
    if config is None:
        config = MASK_CONFIG
    for rule_name in RULE_ORDER:
        if config.get(rule_name):
            text = MASK_RULES[rule_name](text)
    return text


def mask_documents(docs, config=None):
    """对 langchain Document 列表逐页脱敏，原地修改 page_content。"""
    for doc in docs:
        doc.page_content = mask_text(doc.page_content, config)
    return docs


# ======================== 预览工具 ========================

def _preview_text(text, config=None):
    """返回 (原文前N字, 脱敏后前N字, 修改处列表) 的元组。"""
    if config is None:
        config = MASK_CONFIG
    masked = text
    for rule_name in RULE_ORDER:
        if config.get(rule_name):
            masked = MASK_RULES[rule_name](masked)
    changes = []
    # 简单的逐规则对比
    temp = text
    for rule_name in RULE_ORDER:
        if config.get(rule_name):
            after = MASK_RULES[rule_name](temp)
            if after != temp:
                changes.append(f"[{rule_name}] applied")
            temp = after
    return text[:500], masked[:500], changes


def _preview_file(filepath, config=None):
    """预览单个文件的前 5 页脱敏效果。"""
    fp = Path(filepath)
    docs = []

    if fp.suffix.lower() == ".pdf":
        try:
            import pdfplumber
            with pdfplumber.open(str(fp)) as pdf:
                for page in pdf.pages[:5]:
                    text = page.extract_text() or ""
                    if text.strip():
                        # 构造简易 Document 对象以复用预览逻辑
                        class _FakeDoc:
                            pass
                        d = _FakeDoc()
                        d.page_content = text
                        docs.append(d)
        except Exception:
            # pdfplumber 不可用时降级为 PyPDFLoader
            from langchain_community.document_loaders import PyPDFLoader
            docs = PyPDFLoader(str(fp)).load()
    elif fp.suffix.lower() == ".docx":
        from docx import Document as DocxDocument
        doc = DocxDocument(str(fp))
        text = "\n\n".join(p.text for p in doc.paragraphs if p.text and p.text.strip())
        if text:
            class _FakeDoc:
                pass
            d = _FakeDoc()
            d.page_content = text
            docs.append(d)
    else:
        print(f"  unsupported file type: {fp.suffix}")
        return

    print(f"  File: {fp.name}  ({len(docs)} pages/sections)")
    print("=" * 70)

    for i, doc in enumerate(docs[:5]):
        original = doc.page_content[:400]
        masked = mask_text(doc.page_content, config=config)[:400]
        if original.strip():
            print(f"\n--- Page {i+1} ---")
            print(f"[ORI] {original[:350]}")
            print(f"[MSK] {masked[:350]}")
            if original != masked:
                print(f"  >>> 本页有数据被脱敏")
    print()


def preview(data_path, config=None):
    """批量预览 data 目录下所有文档的脱敏效果。"""
    dp = Path(data_path)
    if dp.is_dir():
        for fp in sorted(dp.glob("*")):
            if fp.suffix.lower() in (".pdf", ".docx"):
                _preview_file(str(fp), config)
    else:
        _preview_file(str(dp), config)


# ======================== CLI ========================

if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--preview":
        target = sys.argv[2] if len(sys.argv) >= 3 else "data"
        print("MD Transaction — 脱敏效果预览")
        print(f"  目标: {target}")
        print()
        preview(target)
    else:
        print("用法: python masker.py --preview [文件或目录]")
        print("示例: python masker.py --preview data/")
        print("示例: python masker.py --preview data/某文件.docx")
