## 项目分工

- 项目开发：peng zhou、xinhua wang
- 项目审核：xinhua wang
- 项目报告：mengmeng xu

## 专案简介与动机

### 简介
项目实现了一个完整的可靠数据传输（Reliable Data Transfer, RDT）协议测试框架，包含三种经典协议（Go-Back-N、Selective Repeat、TCP-like）的完整实现和性能比较系统

### 动机
计算机网络领域，可靠数据传输至关重要。不同的RDT协议在性能、实现机理等方面存在明显差异。当前项目目的则为实现：
- 实现机理​：清晰展示GBN、SR和TCP-like协议的工作原理
- ​性能测试​：在不同网络条件下定量比较各协议表现

## 协议设计
### Go-Back-N
- 原理  
GBN采用滑动窗口机制，使用累计确认和超时重传策略。其核心思想是"回退N步"，即当某个包丢失时，重传该包及其后续所有已发送但未确认的包

- 流程图
![gbn](/resource/gbn.png)
### Selective Repeat
- 原理  
    SR协议采用选择性重传机制
    - 每个数据包独立确认和重传
    - 接收方缓存乱序到达的包
    - 每个分组有独立定时器 
- 流程图
![sr](/resource/sr.png)

### TCP-like
- 原理  
    基于TCP核心机制，在 SR 基础上增加 TCP 的三个特性：
    - RTT 动态估计与自适应超时；
    - 三次重复 ACK 触发快速重传；
    - 可选的简单拥塞窗口（cwnd）控制

- 算法  
    - EstimatedRTT = (1−α)EstimatedRTT + α×SampleRTT  
    - DevRTT = (1−β)DevRTT + β×∣SampleRTT − EstimatedRTT∣  
    - RTO = EstimatedRTT + 4×DevRTT  
    α = 0.125, β = 0.25

- 流程图
![tcp-like](/resource/tcp-like.png)

## 实验环境与参数
### 架构设计
- 开发语言：python
- 开发工具：vscode
- 运行环境：ubuntu 22.04 虚拟机运行
- 硬件配置：
    - CPU 2核 2.8GB
    - 内存 4GB

- ​底层​：UnreliableChannel - 网络信道模拟
- ​中间层​：协议实现（GBN、SR、TCP-like）
- ​上层​：实验框架 - 场景管理和性能分析

### 实验参数
| 测试情境 | 封包丢失率 | RTT（ms） | 视窗大小 |
| ------- | ------- | ------- | ------- |
| A | 0% | 50 | 4 |
| B | 10% | 100 | 8 |
| C | 20% | 300 | 4 |
| D | 30% | 500 | 16 |


### 命令示例

```
python3 experiment.py --scenario A --bytes 20000 --runs 2
```
## 结果分析与讨论
### Scenarios A
| Protocol | Time (s) | Throughput (bps) | Retransmissions |
|----------|----------|------------------|-----------------|
| GBN      | 29.536   | 5352             | 459.0           |
| SR       | 5.979    | 26329            | 24.5            |
| TCP-like | 14.811   | 10809            | 29.0            |

![A](/plots/scenario_A.png)
### Scenarios B
| Protocol | Time(s) | Throughput(bps) | Retransmissions |
|----------|---------|----------------|-----------------|
| GBN      | 43.536  | 3539           | 1192.5          |
| SR       | 9.498   | 16885          | 77.5            |
| TCP-like | 49.382  | 3346           | 92.5            |

![B](/plots/scenario_B.png)
### Scenarios C
| Protocol | Time(s) | Throughput(bps) | Retransmissions |
|----------|---------|----------------|-----------------|
| GBN      | 143.258  | 1096          | 672.5           |
| SR       | 65.644   | 2402          | 156.0           |
| TCP-like | 247.898  | 687           | 162.0           |

![C](/plots/scenario_C.png)

### Scenarios D
| Protocol | Time(s) | Throughput(bps) | Retransmissions |
|----------|---------|----------------|-----------------|
| GBN      | 193.882 | 761            | 2046.0          |
| SR       | 23.989   | 6390          | 51.0            |
| TCP-like | 170.157  | 944           | 57.5            |

![D](/plots/scenario_D.png)

## 结论与限制

Scenario A (0% loss, 50ms RTT, window 4):
- All protocols should perform similarly with no packet loss
- Small window size limits throughput  

场景A(0%损耗，50ms RTT，窗口4)：
- 所有协议的性能应该相似，没有丢包
- 小窗口大小限制吞吐量

Scenario B (10% loss, 100ms RTT, window 8):
- Selective Repeat should outperform Go-Back-N
- TCP-like should adapt to conditions

场景B(10%损耗，100ms RTT，窗口8)：
- 选择性重复应该优于Go-Back-N
- 类tcp应该适应条件

Scenario C (20% loss, 300ms RTT, window 4):
- Higher loss and RTT should show protocol robustness differences
- Small window with high loss can cause significant retransmissions

场景C(20%损耗，300ms RTT，窗口4)：
- 更高的损耗和RTT应该显示协议鲁棒性差异
- 高损耗的小窗口可能导致大量重传

Scenario D (5% loss, 500ms RTT, window 16):
- Large window with high delay tests timeout handling
- Should reveal protocol efficiency under delay

场景D(5%损耗，500ms RTT，窗口16)：
- 具有高延迟测试超时处理的大窗口
- 应该显示延迟下的协议效率

## 参考文献（IEEE/ACM格式）