"""Curated knowledge-point catalog for the fixed postgraduate-math question bank."""

from __future__ import annotations

from typing import Any


def _node(
    subject: str,
    chapter: int,
    slug: str,
    title: str,
    hints: tuple[str, ...],
    prerequisites: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": f"kp:{subject}:{slug}",
        "subject": subject,
        "chapter_number": chapter,
        "title": title,
        "hints": hints,
        "prerequisites": prerequisites,
    }


CATALOG: tuple[dict[str, Any], ...] = (
    # Calculus. The duplicated chapter numbers in the imported books are
    # disambiguated by section titles during candidate selection.
    _node("calculus", 1, "function-limit", "函数与极限", ("函数", "极限")),
    _node(
        "calculus", 1, "sequence-limit", "数列极限", ("数列", "数列极限"),
        ("kp:calculus:function-limit",),
    ),
    _node(
        "calculus", 1, "function-limit-continuity", "函数极限与连续性",
        ("函数极限", "连续", "连续性", "无穷小"),
        ("kp:calculus:function-limit",),
    ),
    _node(
        "calculus", 2, "derivative-definition", "导数与微分的定义",
        ("导数定义", "可导", "微分定义"),
        ("kp:calculus:function-limit-continuity",),
    ),
    _node(
        "calculus", 2, "derivative-calculation", "导数与高阶导数计算",
        ("求导", "导数", "高阶导数", "复合函数"),
        ("kp:calculus:derivative-definition",),
    ),
    _node(
        "calculus", 3, "mean-value-theorem", "中值定理",
        ("中值定理", "罗尔", "拉格朗日", "柯西"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 3, "monotonic-extreme", "单调性与极值",
        ("单调", "极值", "最值", "驻点"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 3, "convexity-asymptote", "凹凸性、拐点与渐近线",
        ("凹凸", "拐点", "渐近线"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 4, "space-analytic-geometry", "空间解析几何",
        ("空间解析几何", "直线", "平面", "曲面", "方向向量"),
    ),
    _node(
        "calculus", 4, "derivative-advanced-calculation", "微分学综合计算",
        ("微分学的计算", "参数方程求导", "隐函数求导"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 5, "multivariable-derivative", "多元函数微分学",
        ("多元函数", "偏导数", "全微分", "方向导数", "梯度"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 5, "multivariable-extreme", "多元函数极值与条件极值",
        ("多元极值", "条件极值", "拉格朗日乘数", "二阶偏导"),
        ("kp:calculus:multivariable-derivative",),
    ),
    _node(
        "calculus", 6, "double-integral", "二重积分",
        ("二重积分", "二次积分", "积分区域"),
        ("kp:calculus:single-integral-calculation",),
    ),
    _node(
        "calculus", 6, "triple-integral", "三重积分与重积分应用",
        ("三重积分", "重积分", "体积"),
        ("kp:calculus:double-integral",),
    ),
    _node(
        "calculus", 7, "differential-equation", "微分方程",
        ("微分方程", "微分方程的解", "初值问题"),
        ("kp:calculus:derivative-calculation",),
    ),
    _node(
        "calculus", 7, "first-order-equation", "一阶微分方程",
        ("一阶微分方程", "可分离变量", "一阶线性"),
        ("kp:calculus:differential-equation",),
    ),
    _node(
        "calculus", 8, "series", "无穷级数",
        ("无穷级数", "数项级数", "收敛", "幂级数"),
        ("kp:calculus:sequence-limit",),
    ),
    _node(
        "calculus", 8, "single-integral-concept", "一元函数积分学的概念与性质",
        ("定积分定义", "积分性质", "原函数"),
        ("kp:calculus:function-limit-continuity",),
    ),
    _node(
        "calculus", 9, "single-integral-calculation", "一元函数积分学的计算",
        ("不定积分", "定积分计算", "换元积分", "分部积分"),
        ("kp:calculus:single-integral-concept",),
    ),
    _node(
        "calculus", 9, "line-surface-integral", "曲线积分与曲面积分",
        ("曲线积分", "曲面积分", "格林公式", "高斯公式", "斯托克斯"),
        ("kp:calculus:double-integral",),
    ),
    _node(
        "calculus", 10, "integral-geometry", "积分的几何应用",
        ("旋转体", "弧长", "面积", "几何应用"),
        ("kp:calculus:single-integral-calculation",),
    ),
    _node(
        "calculus", 11, "integral-inequality", "积分等式与积分不等式",
        ("积分等式", "积分不等式", "积分不等式证明"),
        ("kp:calculus:single-integral-calculation",),
    ),
    _node(
        "calculus", 12, "integral-physics", "积分的物理应用",
        ("物理应用", "功", "质量", "力矩", "质心"),
        ("kp:calculus:single-integral-calculation",),
    ),
    _node(
        "calculus", 13, "multivariable-calculus", "多元函数微分学综合",
        ("多元函数微分学", "偏导", "全微分", "梯度"),
        ("kp:calculus:multivariable-derivative",),
    ),
    _node(
        "calculus", 14, "double-integral-advanced", "二重积分综合",
        ("二重积分", "极坐标", "区域变换"),
        ("kp:calculus:double-integral",),
    ),
    _node(
        "calculus", 15, "differential-equation-advanced", "微分方程综合",
        ("微分方程", "二阶微分方程", "线性微分方程"),
        ("kp:calculus:differential-equation",),
    ),
    _node(
        "calculus", 16, "series-advanced", "无穷级数综合",
        ("无穷级数", "幂级数", "傅里叶级数", "收敛半径"),
        ("kp:calculus:series",),
    ),
    _node(
        "calculus", 17, "multivariable-integral-prep", "多元积分学预备知识",
        ("空间曲线", "空间曲面", "向量场", "方向导数"),
        ("kp:calculus:multivariable-derivative",),
    ),
    _node(
        "calculus", 18, "multivariable-integral", "多元函数积分学",
        ("重积分", "曲线积分", "曲面积分", "向量场"),
        ("kp:calculus:double-integral",),
    ),
    # Linear algebra.
    _node("linear_algebra", 10, "determinant", "行列式", ("行列式", "余子式", "代数余子式")),
    _node("linear_algebra", 10, "determinant-calculation", "行列式计算", ("行列式计算", "展开定理", "范德蒙"), ("kp:linear_algebra:determinant",)),
    _node("linear_algebra", 11, "matrix", "矩阵运算", ("矩阵", "矩阵运算", "逆矩阵", "初等变换"), ("kp:linear_algebra:determinant",)),
    _node("linear_algebra", 11, "matrix-rank", "矩阵的秩", ("矩阵的秩", "秩", "满秩"), ("kp:linear_algebra:matrix",)),
    _node("linear_algebra", 12, "vector", "向量与线性表示", ("向量", "线性表示", "线性相关", "线性无关"), ("kp:linear_algebra:matrix",)),
    _node("linear_algebra", 12, "basis-dimension", "向量组的秩与基", ("极大无关组", "基", "维数"), ("kp:linear_algebra:vector",)),
    _node("linear_algebra", 13, "linear-equation", "线性方程组", ("线性方程组", "齐次方程组", "非齐次方程组"), ("kp:linear_algebra:matrix-rank",)),
    _node("linear_algebra", 13, "linear-equation-solution", "方程组解的结构", ("通解", "解的判定", "基础解系"), ("kp:linear_algebra:linear-equation",)),
    _node("linear_algebra", 14, "eigenvalue", "特征值与特征向量", ("特征值", "特征向量", "特征多项式"), ("kp:linear_algebra:matrix",)),
    _node("linear_algebra", 14, "similarity-diagonalization", "相似矩阵与对角化", ("相似", "对角化", "相似变换"), ("kp:linear_algebra:eigenvalue",)),
    _node("linear_algebra", 15, "quadratic-form", "二次型", ("二次型", "规范形", "合同变换"), ("kp:linear_algebra:matrix",)),
    _node("linear_algebra", 15, "positive-definite", "正定二次型", ("正定", "正定矩阵", "顺序主子式"), ("kp:linear_algebra:quadratic-form",)),
    # Probability and mathematical statistics.
    _node("probability", 16, "event-probability", "随机事件与概率", ("随机事件", "概率", "事件运算", "加法公式")),
    _node("probability", 16, "conditional-probability", "条件概率与独立性", ("条件概率", "乘法公式", "全概率", "贝叶斯", "独立"), ("kp:probability:event-probability",)),
    _node("probability", 17, "random-variable", "随机变量及其分布", ("随机变量", "分布函数", "分布律"), ("kp:probability:event-probability",)),
    _node("probability", 17, "common-distribution", "常见分布", ("二项分布", "泊松", "均匀分布", "指数分布", "正态分布"), ("kp:probability:random-variable",)),
    _node("probability", 18, "joint-distribution", "多维随机变量分布", ("二维随机变量", "联合分布", "边缘分布", "条件分布"), ("kp:probability:random-variable",)),
    _node("probability", 18, "random-variable-transformation", "随机变量函数的分布", ("函数分布", "变量变换", "雅可比"), ("kp:probability:joint-distribution",)),
    _node("probability", 19, "expectation-variance", "数学期望与方差", ("数学期望", "方差", "矩", "协方差", "相关系数"), ("kp:probability:random-variable",)),
    _node("probability", 20, "law-large-numbers", "大数定律", ("大数定律", "依概率收敛"), ("kp:probability:expectation-variance",)),
    _node("probability", 20, "central-limit-theorem", "中心极限定理", ("中心极限定理", "标准化", "正态近似"), ("kp:probability:expectation-variance",)),
    _node("probability", 21, "sample-statistics", "数理统计基本概念", ("总体", "样本", "统计量", "抽样分布"), ("kp:probability:random-variable",)),
    _node("probability", 22, "point-estimation", "点估计", ("点估计", "矩估计", "极大似然估计"), ("kp:probability:sample-statistics",)),
    _node("probability", 22, "estimator-quality", "估计量的评价", ("无偏性", "有效性", "一致性"), ("kp:probability:point-estimation",)),
    _node("probability", 23, "hypothesis-test", "假设检验", ("假设检验", "拒绝域", "显著性水平", "检验统计量"), ("kp:probability:sample-statistics",)),
)


def catalog_nodes() -> list[dict[str, Any]]:
    return [dict(item) for item in CATALOG]


def nodes_for_section(
    subject: str,
    chapter_number: int,
    section_title: str,
) -> list[dict[str, Any]]:
    """Return a bounded candidate list for AI classification."""
    title = section_title.replace(" ", "")
    all_subject = [item for item in CATALOG if item["subject"] == subject]
    by_slug = {item["id"].rsplit(":", 1)[-1]: item for item in all_subject}
    title_groups = (
        ("一元函数积分学及其应用", (
            "single-integral-concept",
            "single-integral-calculation",
            "integral-geometry",
            "integral-inequality",
            "integral-physics",
        )),
        ("一元函数微分学及其应用", (
            "derivative-definition",
            "derivative-calculation",
            "mean-value-theorem",
            "monotonic-extreme",
            "convexity-asymptote",
        )),
        ("多元函数微分学及其应用", (
            "multivariable-derivative",
            "multivariable-extreme",
        )),
        ("重积分及其应用", ("double-integral", "triple-integral")),
        ("曲线积分与曲面积分", ("line-surface-integral",)),
        ("微分方程及其应用", ("differential-equation", "first-order-equation")),
        ("无穷级数", ("series", "series-advanced")),
        ("空间解析几何", ("space-analytic-geometry",)),
    )
    for phrase, slugs in title_groups:
        if phrase in title:
            matched = [by_slug[slug] for slug in slugs if slug in by_slug]
            if matched:
                return matched
    nodes = [
        item
        for item in CATALOG
        if item["subject"] == subject and item["chapter_number"] == chapter_number
    ]
    if "空间解析几何" in title:
        nodes = [item for item in nodes if item["id"].endswith("space-analytic-geometry")]
    elif "数列极限" in title:
        nodes = [item for item in nodes if item["id"].endswith("sequence-limit")]
    elif "微分学的计算" in title:
        nodes = [item for item in nodes if item["id"].endswith("advanced-calculation")]
    elif "无穷级数" in title:
        nodes = [item for item in nodes if "series" in item["id"]]
    elif "二重积分" in title:
        nodes = [item for item in nodes if "double-integral" in item["id"]]
    elif "微分方程" in title:
        nodes = [item for item in nodes if "differential-equation" in item["id"]]
    elif "一元函数积分学的计算" in title:
        nodes = [item for item in nodes if item["id"].endswith("single-integral-calculation")]
    elif "行列式" in title:
        nodes = [item for item in nodes if "determinant" in item["id"]]
    return nodes or [
        item for item in CATALOG if item["subject"] == subject and item["chapter_number"] == chapter_number
    ]


def prerequisite_nodes(node_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(node_ids)
    result: list[dict[str, Any]] = []
    for item in CATALOG:
        if item["id"] in wanted:
            for prerequisite in item["prerequisites"]:
                match = next((candidate for candidate in CATALOG if candidate["id"] == prerequisite), None)
                if match and match not in result:
                    result.append(dict(match))
    return result
