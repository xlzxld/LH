[← 第00章](00-学习路线图与环境搭建.md)| **第 01 章 / 共 13 章**| [第02章 →](02-量化核心概念.md) | [目录](../README.md) |

# 第 1 章 · Python 零基础速成

> **学习目标**：不需要成为程序员，只需读得懂本项目代码、改得动参数。
> **耗时**：3~5 天（每天 1 小时）。已经会 Python 的同学跳到 1.7 看"量化专用技能"。

## 1.1 Python 是什么，为什么量化都用它

Python 是一门"人类可读"的编程语言：代码几乎就是英语句子。量化圈选它因为三个生态：
**pandas**（表格数据处理）、**numpy**（数学计算）、**ccxt/akshare**（行情接口）——
本教程的全部代码只靠这几样。

运行 Python 代码的两种方式：

```bash
python hello.py      # 运行整个文件（本项目脚本都是这种）
```

```python
print("hello 量化")   # 单行试验：VS Code 里选中按 Shift+Enter，或用 python 交互模式
```

## 1.2 变量与类型：数据的盒子

```python
price = 4.616            # float 浮点数（带小数）
shares = 21630           # int 整数
symbol = "510300"        # str 字符串（文本）
in_position = True       # bool 真假值

print(f"当前 {symbol} 价格 {price} 元")   # f-string 格式化输出，最常用
```

类型转换新手坑：从接口拿到的数字常是字符串，`"4.616"` 不等于 `4.616`：

```python
float("4.616") + 1      # 5.616 ✔
# "4.616" + 1           # TypeError！字符串不能加数字
```

## 1.3 列表与字典：装数据的容器

```python
# list 列表：有顺序的一串东西
watchlist = ["510300", "512100", "600519"]
watchlist[0]          # "510300"（下标从 0 开始！）
watchlist[-1]         # "600519"（-1 = 最后一个）
watchlist.append("510500")    # 追加

# dict 字典：键值对，量化代码里无处不在
trade = {"side": "BUY", "price": 4.62, "shares": 1000}
trade["price"]        # 4.62
trade["fee"] = 1.15   # 新增键
trade.keys()          # 所有键
```

## 1.4 控制流：让程序做决定

```python
ma_fast, ma_slow = 4.65, 4.60

if ma_fast > ma_slow:
    action = "满仓"       # 缩进就是 Python 的语法！4 个空格
elif ma_fast < ma_slow:
    action = "清仓"
else:
    action = "观望"

for code in watchlist:           # 遍历列表
    print(f"监测 {code}")

i = 0
while i < 3:                     # 条件循环（实盘机器人就是无限 while）
    i += 1
```

比较运算符的结果都是 `True` / `False`，量化判断"金叉/死叉"全靠它们：

```python
4.65 > 4.60    # True（大于）
4.65 == 4.60   # False（== 是比较；= 是赋值，别搞混！）
4.65 != 4.60   # True（!= 是不等于）
4.65 >= 4.60   # True（>= 大于等于，<= 同理）
```

布尔逻辑用 `and` / `or` / `not` 组合多个条件：

```python
(ma_fast > ma_slow) and (volume > 0)   # 两个都满足才是 True
(ma_fast > ma_slow) or (rsi < 30)      # 任一满足即 True
not in_position                          # 取反
```

> ⚠️ 注意：`and`/`or` 用在"单个值"上；到了 pandas 对"一整列数据"做条件判断时，
> 要改用 `&` 和 `|`（第 4 章会正面撞上，这里先记住有这回事）。

## 1.5 函数：把逻辑打包

```python
def dual_ma(prices, fast=3, slow=5):
    """计算双均线信号：快线在上返回 1（满仓），否则 0（空仓）。
       参数带默认值 => 调用时可省略。"""
    ma_fast = sum(prices[-fast:]) / fast   # 最近 fast 天收盘价之和 / fast = 快线均值
    ma_slow = sum(prices[-slow:]) / slow   # 最近 slow 天收盘价之和 / slow = 慢线均值
    return 1 if ma_fast > ma_slow else 0   # 三元表达式：条件为真返回 1，否则 0

prices = [4.1, 4.2, 4.15, 4.3, 4.4, 4.5, 4.6, 4.55, 4.7, 4.8]
dual_ma(prices)                            # 用最近 3 天 vs 最近 5 天均线比大小
```

上面用到的三个基础件（务必认识，后面天天见）：

```python
prices[-fast:]     # 切片：取列表"最后 fast 个"（负号 = 从末尾往前数）
sum(prices[-fast:]) # sum()：把切片里的数字加起来
sum(...) / fast    # 求平均：和 ÷ 个数
```

再加一个 `assert`（断言，第 3 章会用它校验数据）：

```python
assert fast < slow, "快线窗口必须小于慢线"   # 条件为假就报错并停下，帮你尽早发现 bug
```

三个新手必知的习惯：

```python
# 1) 导入模块（用别人造好的轮子）
import pandas as pd          # 约定俗成的缩写
from pathlib import Path     # 只导入需要的类

# 2) 异常处理：网络会断、接口会挂，程序不能一碰就死
try:
    df = fetch_data("510300")
except Exception as exc:
    print(f"获取失败: {exc}")   # 记录后继续跑，别崩

# 3) 主入口写法：本项目每个脚本结尾都有这两行
if __name__ == "__main__":
    main()
```

## 1.6 pandas 最小必备集（量化 90% 的日常）

pandas 的 `DataFrame` 就是一张带行列索引的 Excel 表。行情数据 = 一张表：
每行一个交易日，列是 open/high/low/close/volume。

```python
import pandas as pd

df = pd.read_csv("data/astock_510300.csv", index_col=0, parse_dates=True)

df.head()          # 看前 5 行          df.tail()    看后 5 行
df.shape           # (行数, 列数)
df["close"]        # 取一列 => Series（带索引的一维数组）
df.describe()      # 一键统计摘要
```

量化最常用的 5 个操作：

```python
# 1. 移动平均：过去 20 天收盘价的平均值（所有技术指标都是这么算的）
ma20 = df["close"].rolling(20).mean()

# 2. 涨跌幅：今天比昨天变化百分之几（收益率序列）
returns = df["close"].pct_change()

# 3. 累计乘积：把每日收益率串成净值曲线
equity = (1 + returns).cumprod()

# 4. 布尔筛选：只看大涨的日子
big_up = df[df["close"].pct_change() > 0.03]

# 5. 最大值/回撤相关的累计函数
running_max = df["close"].cummax()      # 历史最高价到今天为止
```

**`.rolling(N)` 和 `pct_change()` 这两个方法，请写 10 遍肌肉记忆。** 第 4 章的策略就靠它们。

## 1.7 面向对象：看懂 `exchange.create_order(...)` 就够了

```python
class Robot:
    def __init__(self, name):        # 构造：new 的时候自动调用
        self.name = name             # self = 对象自己，self.xxx = 挂在自己身上的属性

    def speak(self):                 # 方法：对象会做的事
        return f"{self.name} 在巡检行情"

r = Robot("盯盘机器人")
print(r.speak())
```

你只需要理解：`exchange = ccxt.binance({...})` 创建了一个"交易所对象"，
之后 `exchange.fetch_ticker(...)` 就是叫它做事。第 9 章全是这个套路。

## 1.8 报错不慌：三步定位法

1. **看最后一行**：`KeyError: 'close'` = 字典/表里没有这个键；`ModuleNotFoundError` = 库没装（pip install）；`IndentationError` = 缩进错了。
2. **看倒数第二行**：出错的**你自己写的文件**和行号，点过去看。
3. **复制报错去搜**：99% 的问题别人踩过。

## 动手环节

1. 新建 `my_practice.py`，实现：给定列表 `prices = [3.9, 4.0, 4.2, 4.1, 4.5, 4.7]`，打印最新 3 日均价。
2. 用 1.5 学的切片 + 求和，把 `dual_ma` 改成"最近 5 日 vs 最近 10 日均线"，用练习 1 的 prices 验证输出是 0 还是 1。
3. 用 pandas 读入 `data/astock_510300.csv`，打印：总行数、日期范围、收盘价均值、单日最大涨幅。
4. （可选）安装 jupyter `pip install jupyterlab`，体验笔记本式交互写代码——研究策略时非常好用。
5. （学完第 4 章再回来做）读 `code/ch04_backtest/strategy.py`，把 `dual_ma_weights` 函数逐行用自己的话解释。

## 常见的坑

- `=` 是赋值，`==` 才是比较 —— `if x = 5:` 直接语法错误。
- 下标从 0 开始：`prices[1]` 是第二个元素。
- 浮点精度：`0.1 + 0.2 != 0.3`，比较金额时用 `abs(a-b) < 1e-9` 或 `round()`。
- 改了代码没生效？你可能在两个不同目录开了终端。**永远在项目根目录运行脚本**。
