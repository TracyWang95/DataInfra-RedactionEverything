"""
实体类型管理API
基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》国家标准设计
所有类型都是可配置的，系统预置常用类型供用户使用

标识符分类（参考国标3.6-3.9）：
- 直接标识符：能够单独识别特定自然人的信息
- 准标识符：与其他信息结合可识别特定自然人的信息
- 敏感属性：涉及个人敏感信息的属性

去标识化技术参考国标附录A：
- 统计技术：抑制、聚合、数据交换
- 密码技术：确定性加密、保序加密、保形加密、同态加密
- 抑制技术：删除、屏蔽
- 假名化技术：计数器、随机数生成器、加密哈希函数、消息认证码、对称加密
- 泛化技术：四舍五入、随机舍入、区间泛化、数据截断、顶/底编码
- 随机化技术：噪声添加、置换
"""

from fastapi import APIRouter, HTTPException, status, Query
from typing import List, Dict, Optional, Literal
from pydantic import BaseModel, Field
from enum import Enum
import uuid


router = APIRouter()


class IdentifierCategory(str, Enum):
    """
    标识符类别 - 基于 GB/T 37964-2019 第3.6-3.9节
    """
    DIRECT = "direct"           # 直接标识符：能够单独识别特定自然人
    QUASI = "quasi"             # 准标识符：与其他信息结合可识别特定自然人
    SENSITIVE = "sensitive"     # 敏感属性：涉及敏感信息的属性
    OTHER = "other"             # 其他一般属性


class EntityTypeConfig(BaseModel):
    """
    实体类型配置
    遵循 GB/T 37964-2019 标识符分类体系
    """
    id: str = Field(..., description="唯一ID")
    name: str = Field(..., description="显示名称")
    category: IdentifierCategory = Field(
        default=IdentifierCategory.QUASI, 
        description="标识符类别（GB/T 37964-2019）：direct=直接标识符, quasi=准标识符, sensitive=敏感属性"
    )
    description: Optional[str] = Field(None, description="语义描述，用于指导LLM识别")
    examples: List[str] = Field(default_factory=list, description="示例文本")
    color: str = Field(default="#6B7280", description="前端显示颜色")
    regex_pattern: Optional[str] = Field(None, description="正则表达式（优先使用）")
    use_llm: bool = Field(default=True, description="是否使用LLM识别（无正则时必须为True）")
    enabled: bool = Field(default=True, description="是否启用")
    order: int = Field(default=100, description="排序权重")
    tag_template: Optional[str] = Field(None, description="结构化标签模板，如 <组织[{index}].企业.完整名称>")
    risk_level: int = Field(default=2, description="重标识风险等级 1-5，参考 GB/T 37964-2019 第4.3节")


class EntityTypesResponse(BaseModel):
    """实体类型列表响应"""
    custom_types: List[EntityTypeConfig]
    total: int


class CreateEntityTypeRequest(BaseModel):
    """创建实体类型请求"""
    name: str
    description: Optional[str] = None
    examples: List[str] = []
    color: str = "#6B7280"
    regex_pattern: Optional[str] = None
    use_llm: bool = True
    tag_template: Optional[str] = None


class UpdateEntityTypeRequest(BaseModel):
    """更新实体类型请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    examples: Optional[List[str]] = None
    color: Optional[str] = None
    regex_pattern: Optional[str] = None
    use_llm: Optional[bool] = None
    enabled: Optional[bool] = None
    order: Optional[int] = None
    tag_template: Optional[str] = None


# =============================================================================
# 预置实体类型 - 基于 GB/T 37964-2019《信息安全技术 个人信息去标识化指南》
# =============================================================================
# 
# 标识符分类说明（参考国标第3章术语定义）：
# 
# 1. 直接标识符 (direct): 能够单独识别个人信息主体的标识符
#    - 姓名、身份证号、护照号、社保号、驾驶证号等
#    - 特点：单独出现即可识别个人身份，需要重点保护
#    - 重标识风险：最高
#
# 2. 准标识符 (quasi): 与其他信息结合可识别个人信息主体的标识符  
#    - 年龄、性别、出生日期、邮政编码、职业、教育背景等
#    - 特点：单独出现风险较低，但组合后可能识别个人
#    - 重标识风险：中等，需根据数据集整体评估
#
# 3. 敏感属性 (sensitive): 涉及个人敏感信息的属性
#    - 政治面貌、宗教信仰、健康状况、财务状况、犯罪记录等
#    - 特点：虽不直接标识个人，但泄露会造成严重后果
#    - 保护优先级：高
#
# 去标识化技术参考（国标附录A）：
# - 抑制技术：删除、屏蔽（如 *** 替换）
# - 假名化技术：使用随机化或加密方式替换标识符
# - 泛化技术：区间化、截断、四舍五入
# - 随机化技术：噪声添加、置换
# =============================================================================

PRESET_ENTITY_TYPES: Dict[str, EntityTypeConfig] = {
    
    # =========================================================================
    # 第一类：直接标识符 (Direct Identifiers)
    # GB/T 37964-2019 第3.6节：能够单独识别个人信息主体的标识符
    # =========================================================================
    
    # --- 1.1 自然人标识 ---
    "PERSON": EntityTypeConfig(
        id="PERSON",
        name="姓名",
        category=IdentifierCategory.DIRECT,
        description="自然人姓名，包括中文全名、英文名、曾用名、笔名、艺名、网名、昵称、绰号等一切可标识个人身份的称谓。",
        examples=["张三", "李明华", "王小二", "John Smith", "李某某（曾用名：李大壮）", "老王", "小张", "张总", "Mike Chen"],
        color="#3B82F6",
        use_llm=True,
        tag_template="<姓名[{index}].自然人.全名>",
        order=1,
        risk_level=5,
    ),
    "ID_CARD": EntityTypeConfig(
        id="ID_CARD",
        name="身份证号",
        category=IdentifierCategory.DIRECT,
        description="中国大陆居民身份证号码，18位或15位。含末位X校验码。",
        examples=["110101199003071234", "11010119900307123X", "身份证号码：320102198507152345"],
        color="#EF4444",
        regex_pattern=r'[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]',
        use_llm=False,
        tag_template="<证件号码[{index}].身份证.号码>",
        order=2,
        risk_level=5,
    ),
    "PASSPORT": EntityTypeConfig(
        id="PASSPORT",
        name="护照号",
        category=IdentifierCategory.DIRECT,
        description="护照号码。中国普通护照以E开头、公务护照以G开头，后跟8位数字。含港澳通行证、台湾通行证。",
        examples=["E12345678", "G87654321", "EA1234567", "护照号码：E23456789", "港澳通行证号：C12345678"],
        color="#DC2626",
        regex_pattern=r'[EeGgCc][A-Za-z]?\d{7,8}',
        use_llm=False,
        tag_template="<证件号码[{index}].护照.号码>",
        order=3,
        risk_level=5,
    ),
    "SOCIAL_SECURITY": EntityTypeConfig(
        id="SOCIAL_SECURITY",
        name="社保号/医保号",
        category=IdentifierCategory.DIRECT,
        description="社会保障卡号码、医疗保险号码、公积金账号、养老保险号、失业保险号等社会保障类编号。",
        examples=["社保卡号：12345678901234567", "医保号：310100198901011234", "公积金账号：1234567890", "养老保险号：沪社保1234567890"],
        color="#B91C1C",
        use_llm=True,
        tag_template="<证件号码[{index}].社保卡.号码>",
        order=4,
        risk_level=5,
    ),
    "DRIVER_LICENSE": EntityTypeConfig(
        id="DRIVER_LICENSE",
        name="驾驶证号/行驶证号",
        category=IdentifierCategory.DIRECT,
        description="机动车驾驶证号码（通常与身份证号一致）、行驶证号码、道路运输证号等。",
        examples=["驾驶证号：110101199003071234", "行驶证号：京A12345", "道路运输证号：110000001234"],
        color="#991B1B",
        use_llm=True,
        tag_template="<证件号码[{index}].驾驶证.号码>",
        order=5,
        risk_level=5,
    ),
    "MILITARY_ID": EntityTypeConfig(
        id="MILITARY_ID",
        name="军官证/士兵证号",
        category=IdentifierCategory.DIRECT,
        description="军官证号、士兵证号、军人保障卡号等军队证件号码。",
        examples=["军官证号：军字第2024001234号", "士兵证号：陆字第20240001"],
        color="#7F1D1D",
        use_llm=True,
        tag_template="<证件号码[{index}].军人证件.号码>",
        order=5,
        risk_level=5,
        enabled=False,
    ),
    
    # --- 1.2 通信标识 ---
    "PHONE": EntityTypeConfig(
        id="PHONE",
        name="电话号码",
        category=IdentifierCategory.DIRECT,
        description="手机号码、固定电话号码、传真号码、400/800客服电话等一切电话号码。实名制环境下属于直接标识符。",
        examples=["13812345678", "021-12345678", "010-87654321", "+86-13812345678", "400-123-4567", "传真：021-12345679", "联系电话：138****1234"],
        color="#F97316",
        regex_pattern=r'(?:\+86[-\s]?)?1[3-9]\d{9}|(?:0\d{2,3}[-\s]?)?\d{7,8}|400[-\s]?\d{3,4}[-\s]?\d{4}',
        use_llm=False,
        tag_template="<联系方式[{index}].电话.号码>",
        order=6,
        risk_level=5,
    ),
    "EMAIL": EntityTypeConfig(
        id="EMAIL",
        name="电子邮箱",
        category=IdentifierCategory.DIRECT,
        description="电子邮件地址，包括个人邮箱、工作邮箱、企业邮箱等。",
        examples=["user@example.com", "zhangsan@company.cn", "lisi_2024@163.com", "hr@abc-corp.com.cn", "service@gov.cn"],
        color="#06B6D4",
        regex_pattern=r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}',
        use_llm=False,
        tag_template="<联系方式[{index}].邮箱.地址>",
        order=7,
        risk_level=4,
    ),
    "QQ_WECHAT_ID": EntityTypeConfig(
        id="QQ_WECHAT_ID",
        name="QQ号/微信号",
        category=IdentifierCategory.DIRECT,
        description="QQ号码、微信号、微博ID、抖音号等社交账号。实名制环境下可追溯个人身份。",
        examples=["QQ：123456789", "微信号：zhang_san_123", "微信：wxid_abc123def", "抖音号：douyin_user01"],
        color="#8B5CF6",
        use_llm=True,
        tag_template="<联系方式[{index}].社交账号.ID>",
        order=7,
        risk_level=4,
    ),
    
    # --- 1.3 金融账户标识 ---
    "BANK_CARD": EntityTypeConfig(
        id="BANK_CARD",
        name="银行卡号",
        category=IdentifierCategory.DIRECT,
        description="银行借记卡、信用卡卡号，16-19位数字。含VISA、MasterCard、银联卡号。",
        examples=["6222021234567890123", "4367421234567890", "6228480012345678901", "卡号：6225880123456789", "信用卡：5200 1234 5678 9012"],
        color="#EC4899",
        regex_pattern=r'(?:62|4|5)\d{14,17}',
        use_llm=False,
        tag_template="<金融账户[{index}].银行卡.号码>",
        order=8,
        risk_level=5,
    ),
    "BANK_ACCOUNT": EntityTypeConfig(
        id="BANK_ACCOUNT",
        name="银行账号",
        category=IdentifierCategory.DIRECT,
        description="银行存款账号、对公账号、结算账号、保证金账号等数字账号。",
        examples=["账号：1234567890123456789", "对公账号：11001234567890", "收款账号：6217 0000 1234 5678 901", "结算账号：3100 1234 5678"],
        color="#DB2777",
        use_llm=True,
        tag_template="<金融账户[{index}].银行账号.号码>",
        order=9,
        risk_level=5,
    ),
    "BANK_NAME": EntityTypeConfig(
        id="BANK_NAME",
        name="开户行/银行名称",
        category=IdentifierCategory.DIRECT,
        description="开户银行全称、支行名称、银行机构名。在法律文书和合同中常与账号配对出现。",
        examples=["开户行：中国工商银行北京朝阳支行", "招商银行深圳南山支行", "中国建设银行XX分行营业部", "开户银行：中国农业银行XX支行"],
        color="#7C3AED",
        use_llm=True,
        tag_template="<金融账户[{index}].开户行.名称>",
        order=9,
        risk_level=4,
    ),
    "PAYMENT_ACCOUNT": EntityTypeConfig(
        id="PAYMENT_ACCOUNT",
        name="支付账号",
        category=IdentifierCategory.DIRECT,
        description="微信支付、支付宝、PayPal、数字货币钱包地址等第三方支付和数字资产账户。",
        examples=["支付宝：user@example.com", "微信支付：138****1234", "PayPal：user@email.com", "USDT地址：TN...xyz", "数字人民币钱包号：xxxx"],
        color="#BE185D",
        use_llm=True,
        tag_template="<金融账户[{index}].支付账号.账号>",
        order=10,
        risk_level=4,
    ),
    "TAX_ID": EntityTypeConfig(
        id="TAX_ID",
        name="纳税人识别号",
        category=IdentifierCategory.DIRECT,
        description="纳税人识别号、税务登记号。企业为统一社会信用代码，个人为身份证号。",
        examples=["纳税人识别号：91110000100000000X", "税号：110101199003071234", "纳税识别号：91310000XXXXXXXXXX"],
        color="#C2410C",
        use_llm=True,
        tag_template="<金融账户[{index}].税号.号码>",
        order=10,
        risk_level=4,
    ),
    
    # --- 1.4 网络标识 ---
    "IP_ADDRESS": EntityTypeConfig(
        id="IP_ADDRESS",
        name="IP地址",
        category=IdentifierCategory.DIRECT,
        description="互联网协议地址，IPv4或IPv6。可追溯到特定设备，属于直接标识符。",
        examples=["192.168.1.1", "10.0.0.1", "2001:0db8:85a3:0000:0000:8a2e:0370:7334"],
        color="#7C3AED",
        regex_pattern=r'(?:\d{1,3}\.){3}\d{1,3}|(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}',
        use_llm=False,
        tag_template="<网络标识[{index}].IP地址.地址>",
        order=11,
        risk_level=4,
    ),
    "MAC_ADDRESS": EntityTypeConfig(
        id="MAC_ADDRESS",
        name="MAC地址",
        category=IdentifierCategory.DIRECT,
        description="网卡物理地址，设备唯一标识。属于直接标识符。",
        examples=["00:1A:2B:3C:4D:5E", "00-1A-2B-3C-4D-5E"],
        color="#6D28D9",
        regex_pattern=r'(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}',
        use_llm=False,
        tag_template="<网络标识[{index}].MAC地址.地址>",
        order=12,
        risk_level=4,
    ),
    "DEVICE_ID": EntityTypeConfig(
        id="DEVICE_ID",
        name="设备标识",
        category=IdentifierCategory.DIRECT,
        description="IMEI、IMSI、设备序列号等设备唯一标识符。属于直接标识符。",
        examples=["IMEI: 123456789012345", "设备序列号：ABC123XYZ"],
        color="#5B21B6",
        use_llm=True,
        tag_template="<网络标识[{index}].设备ID.标识>",
        order=13,
        risk_level=4,
    ),
    
    # --- 1.5 生物特征标识 ---
    "BIOMETRIC": EntityTypeConfig(
        id="BIOMETRIC",
        name="生物特征",
        category=IdentifierCategory.DIRECT,
        description="指纹、虹膜、面部特征、声纹、DNA、步态等生物识别信息的文字描述。不可变更，终身有效。",
        examples=["指纹编号：F001234", "人脸识别ID：FACE_20240101_001", "DNA鉴定编号：DNA2024001", "声纹特征码：VP_001"],
        color="#4C1D95",
        use_llm=True,
        tag_template="<生物特征[{index}].类型.标识>",
        order=14,
        risk_level=5,
    ),
    "USERNAME_PASSWORD": EntityTypeConfig(
        id="USERNAME_PASSWORD",
        name="用户名/密码",
        category=IdentifierCategory.DIRECT,
        description="登录用户名、密码、PIN码、验证码、密钥、Token等认证凭据。泄露后可直接导致账户被盗。",
        examples=["用户名：admin", "密码：P@ssw0rd123", "PIN码：123456", "API Key：sk-xxxx", "Token：eyJhbG..."],
        color="#450A0A",
        use_llm=True,
        tag_template="<认证凭据[{index}].类型.内容>",
        order=15,
        risk_level=5,
    ),
    
    # =========================================================================
    # 第二类：准标识符 (Quasi-Identifiers)
    # GB/T 37964-2019 第3.7节：与其他信息结合可识别个人信息主体的标识符
    # =========================================================================
    
    # --- 2.1 人口统计学信息 ---
    "BIRTH_DATE": EntityTypeConfig(
        id="BIRTH_DATE",
        name="出生日期",
        category=IdentifierCategory.QUASI,
        description="出生年月日。单独不能识别个人，但与其他信息组合可能识别。",
        examples=["1990年3月7日", "出生于1985-06-15", "生日：03/07", "出生日期：一九九零年三月七日"],
        color="#84CC16",
        regex_pattern=r'(?:出生[于日期：:]*|生日[：:]*)?\d{4}[-年/]\d{1,2}[-月/]\d{1,2}[日]?',
        use_llm=True,
        tag_template="<人口统计[{index}].出生日期.日期>",
        order=20,
        risk_level=3,
    ),
    "AGE": EntityTypeConfig(
        id="AGE",
        name="年龄",
        category=IdentifierCategory.QUASI,
        description="个人年龄信息，包括周岁、虚岁等表述。",
        examples=["35岁", "现年42岁", "年龄：28", "时年56周岁", "年仅18岁"],
        color="#A3E635",
        use_llm=True,
        tag_template="<人口统计[{index}].年龄.数值>",
        order=21,
        risk_level=2,
    ),
    "GENDER": EntityTypeConfig(
        id="GENDER",
        name="性别",
        category=IdentifierCategory.QUASI,
        description="个人性别信息。",
        examples=["男", "女", "性别：男性", "女性", "男，汉族"],
        color="#BEF264",
        use_llm=True,
        tag_template="<人口统计[{index}].性别.类型>",
        order=22,
        risk_level=1,
    ),
    "NATIONALITY": EntityTypeConfig(
        id="NATIONALITY",
        name="国籍/民族",
        category=IdentifierCategory.QUASI,
        description="国籍、民族、籍贯、户籍所在地等信息。",
        examples=["中国", "汉族", "国籍：美国", "民族：回族", "籍贯：湖南长沙", "户籍：北京市朝阳区"],
        color="#D9F99D",
        use_llm=True,
        tag_template="<人口统计[{index}].国籍民族.类型>",
        order=23,
        risk_level=2,
    ),
    "MARITAL_STATUS": EntityTypeConfig(
        id="MARITAL_STATUS",
        name="婚姻状况",
        category=IdentifierCategory.QUASI,
        description="婚姻状况、家庭关系等信息。",
        examples=["已婚", "未婚", "离异", "丧偶", "婚姻状况：已婚", "配偶：张某"],
        color="#C084FC",
        use_llm=True,
        tag_template="<人口统计[{index}].婚姻状况.类型>",
        order=23,
        risk_level=2,
        enabled=False,
    ),
    
    # --- 2.2 地理位置信息 ---
    "ADDRESS": EntityTypeConfig(
        id="ADDRESS",
        name="详细地址",
        category=IdentifierCategory.QUASI,
        description="详细地址，包括省市区街道门牌号、小区楼栋单元室号、工业园区、写字楼等。含住址、户籍地、经营地址、送达地址等。",
        examples=["北京市朝阳区某某路123号", "上海市浦东新区某某街道某某小区1栋101室", "住所地：广州市天河区珠江新城XX大厦2001室",
                  "经营地址：深圳市南山区科技园XX号", "送达地址：杭州市西湖区XX路XX号", "户籍地：四川省成都市武侯区XX街XX号"],
        color="#6366F1",
        use_llm=True,
        tag_template="<地理位置[{index}].详细地址.完整地址>",
        order=24,
        risk_level=4,
    ),
    "POSTAL_CODE": EntityTypeConfig(
        id="POSTAL_CODE",
        name="邮政编码",
        category=IdentifierCategory.QUASI,
        description="邮政编码。属于准标识符，可缩小地理范围。",
        examples=["100000", "200001", "邮编：510000"],
        color="#818CF8",
        regex_pattern=r'(?:邮编[：:]*)?\d{6}',
        use_llm=False,
        tag_template="<地理位置[{index}].邮编.编码>",
        order=25,
        risk_level=2,
    ),
    "GPS_LOCATION": EntityTypeConfig(
        id="GPS_LOCATION",
        name="GPS坐标",
        category=IdentifierCategory.QUASI,
        description="GPS经纬度坐标。精确坐标可能识别特定位置，属于准标识符。",
        examples=["39.9042° N, 116.4074° E", "经度：116.4074 纬度：39.9042"],
        color="#A5B4FC",
        regex_pattern=r'[\d.]+°?\s*[NS]?,?\s*[\d.]+°?\s*[EW]?|[经纬]度[：:]\s*[\d.]+',
        use_llm=True,
        tag_template="<地理位置[{index}].GPS坐标.坐标>",
        order=26,
        risk_level=3,
    ),
    
    # --- 2.3 职业与教育信息 ---
    "OCCUPATION": EntityTypeConfig(
        id="OCCUPATION",
        name="职业/职务",
        category=IdentifierCategory.QUASI,
        description="职业、职务、工作岗位等。属于准标识符。",
        examples=["软件工程师", "总经理", "职务：财务总监"],
        color="#F472B6",
        use_llm=True,
        tag_template="<职业教育[{index}].职业.名称>",
        order=27,
        risk_level=2,
    ),
    "EDUCATION": EntityTypeConfig(
        id="EDUCATION",
        name="教育背景",
        category=IdentifierCategory.QUASI,
        description="学历、毕业院校、专业等教育信息。属于准标识符。",
        examples=["本科", "清华大学计算机系", "学历：硕士研究生"],
        color="#F9A8D4",
        use_llm=True,
        tag_template="<职业教育[{index}].学历.类型>",
        order=28,
        risk_level=2,
    ),
    "WORK_UNIT": EntityTypeConfig(
        id="WORK_UNIT",
        name="工作单位",
        category=IdentifierCategory.QUASI,
        description="所在公司、机构、单位名称。可缩小识别范围，属于准标识符。",
        examples=["某某科技有限公司", "某市人民医院", "工作单位：某银行某支行"],
        color="#FBCFE8",
        use_llm=True,
        tag_template="<职业教育[{index}].单位.名称>",
        order=29,
        risk_level=3,
    ),
    
    # --- 2.4 时间信息 ---
    "DATE": EntityTypeConfig(
        id="DATE",
        name="日期",
        category=IdentifierCategory.QUASI,
        description="事件发生日期等时间信息。属于准标识符。",
        examples=["2024年1月15日", "2024-01-15", "签订日期：2024/3/20"],
        color="#22D3EE",
        regex_pattern=r'\d{4}年\d{1,2}月\d{1,2}日|\d{4}[-/]\d{1,2}[-/]\d{1,2}',
        use_llm=False,
        tag_template="<时间信息[{index}].日期.年月日>",
        order=30,
        risk_level=2,
    ),
    "TIME": EntityTypeConfig(
        id="TIME",
        name="时间",
        category=IdentifierCategory.QUASI,
        description="具体时刻信息。属于准标识符。",
        examples=["14:30:00", "下午3点15分", "时间：08:00"],
        color="#67E8F9",
        regex_pattern=r'\d{1,2}[:：]\d{2}(?:[:：]\d{2})?|[上下]午\d{1,2}[点时]\d{0,2}分?',
        use_llm=True,
        tag_template="<时间信息[{index}].时刻.时分>",
        order=31,
        risk_level=1,
    ),
    
    # --- 2.5 车辆信息 ---
    "LICENSE_PLATE": EntityTypeConfig(
        id="LICENSE_PLATE",
        name="车牌号",
        category=IdentifierCategory.QUASI,
        description="机动车号牌。通过车辆登记信息可追溯到个人，属于准标识符。",
        examples=["京A12345", "沪B67890", "粤AD12345"],
        color="#14B8A6",
        regex_pattern=r'[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领][A-Z][A-Z0-9]{5,6}',
        use_llm=False,
        tag_template="<车辆信息[{index}].车牌.号码>",
        order=32,
        risk_level=3,
    ),
    "VIN": EntityTypeConfig(
        id="VIN",
        name="车架号/VIN",
        category=IdentifierCategory.QUASI,
        description="车辆识别代号，17位字符。属于准标识符。",
        examples=["LVHRU1869K5012345", "车架号：WBA1234567890ABCD"],
        color="#2DD4BF",
        regex_pattern=r'[A-HJ-NPR-Z0-9]{17}',
        use_llm=True,
        tag_template="<车辆信息[{index}].车架号.号码>",
        order=33,
        risk_level=3,
    ),
    
    # =========================================================================
    # 第三类：敏感属性 (Sensitive Attributes)
    # GB/T 37964-2019 第3.8节：涉及敏感信息的属性
    # =========================================================================
    
    # --- 3.1 健康医疗信息 ---
    "HEALTH_INFO": EntityTypeConfig(
        id="HEALTH_INFO",
        name="健康/医疗信息",
        category=IdentifierCategory.SENSITIVE,
        description="疾病诊断、病史、体检结果、用药记录、手术记录、残疾等级、精神状态等健康医疗信息。",
        examples=["诊断：高血压", "患有糖尿病", "病史：心脏病", "术后恢复中", "残疾等级：二级", "精神状态：抑郁症", "血型：O型", "HIV阳性"],
        color="#F87171",
        use_llm=True,
        tag_template="<敏感信息[{index}].健康.描述>",
        order=40,
        risk_level=4,
    ),
    "MEDICAL_RECORD": EntityTypeConfig(
        id="MEDICAL_RECORD",
        name="病历号/就诊号",
        category=IdentifierCategory.SENSITIVE,
        description="医院病历号、门诊号、住院号、处方编号、检验报告编号等医疗编号。",
        examples=["病历号：2024010001", "住院号：H20240115001", "处方编号：RX20240101001", "检验报告号：LAB2024001"],
        color="#FCA5A5",
        use_llm=True,
        tag_template="<敏感信息[{index}].病历号.号码>",
        order=41,
        risk_level=4,
    ),
    
    # --- 3.2 财务信息 ---
    "AMOUNT": EntityTypeConfig(
        id="AMOUNT",
        name="金额/财务数据",
        category=IdentifierCategory.SENSITIVE,
        description="涉案金额、工资收入、奖金、借款金额、赔偿金额、违约金、利息、财产价值等一切财务数字。含大写金额。",
        examples=["人民币10万元", "500,000元", "工资：15000元/月", "叁拾万元整", "借款本金50万元",
                  "违约金10%", "利息3.85%", "赔偿金额：￥200,000.00", "月租金8000元"],
        color="#F43F5E",
        use_llm=True,
        tag_template="<财务信息[{index}].金额.数值>",
        order=42,
        risk_level=3,
    ),
    "PROPERTY": EntityTypeConfig(
        id="PROPERTY",
        name="财产/资产信息",
        category=IdentifierCategory.SENSITIVE,
        description="房产、车辆、股权、存款、投资、保险、知识产权等财产和资产信息描述。含房产证号、不动产权证号。",
        examples=["房产位于某小区", "持有某公司30%股权", "名下有房产3处", "不动产权证号：京(2024)朝阳区不动产权第001号",
                  "车辆：京A12345", "存款余额：100万元", "保单号：PICC2024001"],
        color="#FB7185",
        use_llm=True,
        tag_template="<财务信息[{index}].财产.描述>",
        order=43,
        risk_level=3,
    ),
    
    # --- 3.3 法律相关信息 ---
    "CRIMINAL_RECORD": EntityTypeConfig(
        id="CRIMINAL_RECORD",
        name="犯罪/违法记录",
        category=IdentifierCategory.SENSITIVE,
        description="违法犯罪记录、刑事处罚、行政处罚、纪律处分、失信记录、限制消费令等。",
        examples=["曾因盗窃罪被判处有期徒刑", "有前科", "曾被行政拘留", "列入失信被执行人名单",
                  "被限制高消费", "受到党内警告处分", "吊销营业执照"],
        color="#E11D48",
        use_llm=True,
        tag_template="<敏感信息[{index}].犯罪记录.描述>",
        order=44,
        risk_level=5,
    ),
    
    # --- 3.4 意识形态信息 ---
    "POLITICAL": EntityTypeConfig(
        id="POLITICAL",
        name="政治面貌",
        category=IdentifierCategory.SENSITIVE,
        description="政治面貌、党派成员身份、政治观点等。",
        examples=["中共党员", "民主党派成员", "政治面貌：群众", "九三学社社员", "无党派人士"],
        color="#BE123C",
        use_llm=True,
        tag_template="<敏感信息[{index}].政治面貌.类型>",
        order=45,
        risk_level=3,
    ),
    "RELIGION": EntityTypeConfig(
        id="RELIGION",
        name="宗教信仰",
        category=IdentifierCategory.SENSITIVE,
        description="宗教信仰、宗教活动、宗教团体成员身份等信息。",
        examples=["信仰佛教", "基督教徒", "无宗教信仰", "伊斯兰教", "天主教"],
        color="#9F1239",
        use_llm=True,
        tag_template="<敏感信息[{index}].宗教信仰.类型>",
        order=46,
        risk_level=3,
    ),
    "SEXUAL_ORIENTATION": EntityTypeConfig(
        id="SEXUAL_ORIENTATION",
        name="性取向/性别认同",
        category=IdentifierCategory.SENSITIVE,
        description="性取向、性别认同等极度敏感个人信息。",
        examples=["同性恋", "双性恋", "跨性别"],
        color="#831843",
        use_llm=True,
        tag_template="<敏感信息[{index}].性取向.类型>",
        order=47,
        risk_level=5,
        enabled=False,
    ),
    
    # =========================================================================
    # 第四类：法律文书特有字段
    # 针对法律领域的特殊标识符
    # =========================================================================
    
    # --- 4.1 案件信息 ---
    "CASE_NUMBER": EntityTypeConfig(
        id="CASE_NUMBER",
        name="案件编号",
        category=IdentifierCategory.QUASI,
        description="法院案件编号。含民事、刑事、行政、执行等各类案号。也包括仲裁案号、公证书编号。",
        examples=["(2024)京01民初123号", "(2023)沪0115民初9876号", "(2024)京仲裁字第001号",
                  "公证书编号：(2024)京证字第001号", "执行案号：(2024)京01执123号"],
        color="#8B5CF6",
        regex_pattern=r'[\(（]\d{4}[\)）][京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼使领A-Za-z]{1,4}\d{0,4}[民刑行执破知赔财商劳仲][初终复再抗申裁监督撤]?\d+号',
        use_llm=False,
        tag_template="<案件信息[{index}].案号.编号>",
        order=50,
        risk_level=3,
    ),
    "CONTRACT_NO": EntityTypeConfig(
        id="CONTRACT_NO",
        name="合同/协议编号",
        category=IdentifierCategory.QUASI,
        description="合同、协议、订单、发票的编号。含借款合同号、保险单号、工程合同号等。",
        examples=["合同编号：HT-2024-001", "协议编号：XY20240115", "借款合同号：DK2024001",
                  "保单号：PICC2024001234", "订单号：ORD20240101001", "发票号码：01234567"],
        color="#64748B",
        use_llm=True,
        tag_template="<法律文书[{index}].合同编号.代码>",
        order=51,
        risk_level=2,
    ),
    "LEGAL_DOC_NO": EntityTypeConfig(
        id="LEGAL_DOC_NO",
        name="法律文书编号",
        category=IdentifierCategory.QUASI,
        description="判决书编号、裁定书编号、调解书编号、执行通知书编号、律师函编号等法律文书的文号。",
        examples=["判决书文号：(2024)京01民终123号", "裁定书：(2024)京01民初456号之一",
                  "律师函编号：京律函字[2024]第001号", "执行通知书：(2024)京01执通001号"],
        color="#475569",
        use_llm=True,
        tag_template="<法律文书[{index}].文书编号.编号>",
        order=51,
        risk_level=2,
    ),
    
    # --- 4.2 诉讼参与人 ---
    "LEGAL_PARTY": EntityTypeConfig(
        id="LEGAL_PARTY",
        name="案件当事人",
        category=IdentifierCategory.DIRECT,
        description="法律文书中的原告、被告、申请人、被申请人、上诉人、被上诉人、第三人、债权人、债务人等当事人。",
        examples=["原告张三", "被告某公司", "申请人李四", "被上诉人王五", "第三人赵六",
                  "债权人：某某银行", "债务人：张某某", "反诉原告", "被执行人"],
        color="#F59E0B",
        use_llm=True,
        tag_template="<诉讼参与人[{index}].当事人.姓名>",
        order=52,
        risk_level=5,
    ),
    "LAWYER": EntityTypeConfig(
        id="LAWYER",
        name="律师/代理人",
        category=IdentifierCategory.DIRECT,
        description="委托代理人、辩护人、律师姓名及其所属律所。含法律援助律师、公司法务。",
        examples=["北京某某律师事务所律师张三", "委托代理人李四", "辩护人：王某某（北京XX律所）",
                  "特别授权代理人：赵律师", "法律援助律师：刘某"],
        color="#A855F7",
        use_llm=True,
        tag_template="<诉讼参与人[{index}].律师.姓名>",
        order=53,
        risk_level=4,
    ),
    "JUDGE": EntityTypeConfig(
        id="JUDGE",
        name="法官/书记员",
        category=IdentifierCategory.DIRECT,
        description="审判长、审判员、书记员、人民陪审员、执行法官、法官助理姓名。",
        examples=["审判长：张某某", "书记员：李某", "人民陪审员：王某", "审判员：赵某某",
                  "执行法官：钱某", "法官助理：孙某"],
        color="#0EA5E9",
        use_llm=True,
        tag_template="<诉讼参与人[{index}].司法人员.姓名>",
        order=54,
        risk_level=4,
    ),
    "WITNESS": EntityTypeConfig(
        id="WITNESS",
        name="证人/鉴定人",
        category=IdentifierCategory.DIRECT,
        description="证人、鉴定人、评估人、翻译人员等诉讼参与人姓名。",
        examples=["证人张某", "证人李某某", "鉴定人：王某某", "评估师：赵某", "翻译人员：孙某某"],
        color="#78716C",
        use_llm=True,
        tag_template="<诉讼参与人[{index}].证人.姓名>",
        order=55,
        risk_level=4,
    ),
    
    # --- 4.3 机构信息 ---
    "ORG": EntityTypeConfig(
        id="ORG",
        name="机构/单位名称",
        category=IdentifierCategory.QUASI,
        description="公司、组织、政府机构、法院、律所、银行、医院、学校等单位名称。含简称和全称。",
        examples=["北京某某科技有限公司", "某某市中级人民法院", "某某银行", "腾讯", "阿里巴巴",
                  "北京市朝阳区人民检察院", "某某律师事务所", "某某市公安局XX分局", "XX大学附属医院"],
        color="#10B981",
        use_llm=True,
        tag_template="<机构信息[{index}].名称.全称>",
        order=56,
        risk_level=3,
    ),
    "COMPANY_CODE": EntityTypeConfig(
        id="COMPANY_CODE",
        name="统一社会信用代码",
        category=IdentifierCategory.QUASI,
        description="企业统一社会信用代码（18位）、营业执照注册号、组织机构代码等企业标识编号。",
        examples=["91110000100000000X", "统一社会信用代码：91310000XXXXXXXXXX", "注册号：110000001234567",
                  "组织机构代码：12345678-9"],
        color="#059669",
        regex_pattern=r'[0-9A-Z]{18}',
        use_llm=True,
        tag_template="<机构信息[{index}].信用代码.编号>",
        order=57,
        risk_level=3,
    ),
    "URL_WEBSITE": EntityTypeConfig(
        id="URL_WEBSITE",
        name="网址/链接",
        category=IdentifierCategory.QUASI,
        description="网站URL、下载链接、内网地址等。可能暴露内部系统或个人网站。",
        examples=["https://www.example.com", "http://192.168.1.1/admin", "ftp://files.company.cn/docs"],
        color="#0891B2",
        regex_pattern=r'https?://[^\s<>"{}|\\^`\[\]]+',
        use_llm=False,
        tag_template="<网络信息[{index}].网址.URL>",
        order=58,
        risk_level=2,
    ),
}

# 内存存储（生产环境应改为数据库）
entity_types_db: Dict[str, EntityTypeConfig] = PRESET_ENTITY_TYPES.copy()


@router.get("/custom-types", response_model=EntityTypesResponse)
async def get_entity_types(enabled_only: bool = Query(False, description="是否只返回启用的类型")):
    """
    获取所有实体类型配置
    """
    types = list(entity_types_db.values())
    
    if enabled_only:
        types = [t for t in types if t.enabled]
    
    # 按order排序
    types.sort(key=lambda x: x.order)
    
    return EntityTypesResponse(
        custom_types=types,
        total=len(types)
    )


@router.get("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def get_entity_type(type_id: str):
    """获取单个实体类型配置"""
    if type_id not in entity_types_db:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    return entity_types_db[type_id]


@router.post("/custom-types", response_model=EntityTypeConfig)
async def create_entity_type(request: CreateEntityTypeRequest):
    """创建新的实体类型"""
    # 生成ID
    type_id = f"custom_{uuid.uuid4().hex[:8]}"
    
    new_type = EntityTypeConfig(
        id=type_id,
        name=request.name,
        description=request.description,
        examples=request.examples,
        color=request.color,
        regex_pattern=request.regex_pattern,
        use_llm=request.use_llm,
        tag_template=request.tag_template,
        enabled=True,
        order=200,  # 自定义类型排在后面
    )
    
    entity_types_db[type_id] = new_type
    return new_type


@router.put("/custom-types/{type_id}", response_model=EntityTypeConfig)
async def update_entity_type(type_id: str, request: UpdateEntityTypeRequest):
    """更新实体类型配置"""
    if type_id not in entity_types_db:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    
    existing = entity_types_db[type_id]
    update_data = request.dict(exclude_unset=True)
    
    for key, value in update_data.items():
        setattr(existing, key, value)
    
    entity_types_db[type_id] = existing
    return existing


@router.delete("/custom-types/{type_id}")
async def delete_entity_type(type_id: str):
    """删除实体类型（预置类型只能禁用，不能删除）"""
    if type_id not in entity_types_db:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    
    # 预置类型不允许删除
    if type_id in PRESET_ENTITY_TYPES:
        raise HTTPException(status_code=400, detail="预置类型不能删除，只能禁用")
    
    del entity_types_db[type_id]
    return {"message": "删除成功"}


@router.post("/custom-types/{type_id}/toggle")
async def toggle_entity_type(type_id: str):
    """切换实体类型的启用状态"""
    if type_id not in entity_types_db:
        raise HTTPException(status_code=404, detail="实体类型不存在")
    
    entity_types_db[type_id].enabled = not entity_types_db[type_id].enabled
    return {"enabled": entity_types_db[type_id].enabled}


@router.post("/custom-types/reset")
async def reset_entity_types():
    """重置为预置配置"""
    global entity_types_db
    entity_types_db = PRESET_ENTITY_TYPES.copy()
    return {"message": "已重置为默认配置"}


def get_enabled_types() -> List[EntityTypeConfig]:
    """获取所有启用的实体类型"""
    return [t for t in entity_types_db.values() if t.enabled]


def get_regex_types() -> List[EntityTypeConfig]:
    """获取使用正则识别的类型"""
    return [t for t in entity_types_db.values() if t.enabled and t.regex_pattern]


def get_llm_types() -> List[EntityTypeConfig]:
    """获取使用LLM识别的类型"""
    return [t for t in entity_types_db.values() if t.enabled and t.use_llm]
