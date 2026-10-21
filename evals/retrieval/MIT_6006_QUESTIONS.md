# MIT 6.006 retrieval 测试题（25 题）

课程：[MIT 6.006 Introduction to Algorithms, Spring 2020](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/pages/lecture-notes/)。题目为本项目编写的学生口吻英文问法，不是真实学生问答记录。中文为人工核对用的答案要点和定位。

页码均为 PDF 阅读器从 1 开始的实际页序；包含文件末尾的 OCW 署名页。`mit_6006.json` 是机器可读的唯一标签来源。本表与该文件对应。

| ID | 学生问题 | 正确来源 / PDF 页码 | 段落定位 | 答案要点（不是逐字标准答案） |
| --- | --- | --- | --- | --- |
| H01 | My student IDs are huge numbers but I only have a few thousand students. Why is using each ID as an array index wasteful? | MIT6_006S20_lec4.pdf / 2 | Direct Access Array，小节末尾的空间开销说明 | 按键空间大小分配数组，空间取决于 u 而非实际人数 n。 |
| H02 | Two different keys land in the same bucket. How does chaining let me keep both? | MIT6_006S20_lec4.pdf / 3 | Chaining 小节首两条 | 让桶指向另一数据结构，保存落入该桶的多个元素。 |
| H03 | I use key modulo table size. Why doesn't that alone guarantee fast lookups for every input? | MIT6_006S20_lec4.pdf / 3 | Hash Functions 下 Division 小节，固定函数的坏输入 | 固定函数总可能遇到大量碰撞的输入；表大小和键的分布会影响链长。 |
| H04 | When we randomize the hash function, what exactly is random in the expected constant-time claim? | MIT6_006S20_lec4.pdf / 4 | Universal 小节的概率界与期望链长推导 | 对函数族中随机选择的函数取期望，而非假设输入键随机；装载因子须有界。 |
| H05 | A hash table resize is expensive. How can insertions still be called constant time? | MIT6_006S20_lec4.pdf / 4 | Dynamic 小节三条 | 重建代价分摊到多次动态操作；结论是期望摊还常数时间。 |
| B01 | On a one-way road map, are the roads into a junction the same list as the roads out? | MIT6_006S20_lec9.pdf / 2 | Neighbor Sets/Adjacencies 首两条 | 有向图分别记录入邻居和出邻居；两者通常不同。 |
| B02 | Why does storing a graph as neighbor lists take space for both vertices and edges? | MIT6_006S20_lec9.pdf / 2 | Graph Representations 的结构大小与握手引理推导 | 顶点映射占 O(V)，所有邻接表合计占 O(E)。 |
| B03 | I need routes from one start to every destination. Do I have to store a separate full route for each? | MIT6_006S20_lec9.pdf / 3 | Shortest Paths Tree 小节 | 保存每个可达顶点的前驱即可重建路径，树大小为 O(V)。 |
| B04 | Every move in my puzzle costs one step. How can I find the fewest moves without trying every possible route? | MIT6_006S20_lec9.pdf / 4 | Breadth-First Search 的 level sets 与逐层扩展 | BFS 按距离逐层扩展，首次发现时设置距离与父节点。 |
| B05 | My BFS never reaches one vertex. What distance should I report for it? | MIT6_006S20_lec9.pdf / 4 | BFS 初始化括号及遍历结束时的距离处理 | 不可达顶点的距离为无穷大。 |
| D01 | DFS found me a route. Can I assume it's the route with the fewest edges? | MIT6_006S20_lec10.pdf / 2 | Depth-First Search 开头对返回树的说明 | 不能；DFS 保证可达性，不保证最短路径。 |
| D02 | A search from one vertex misses a separate island of vertices. How do I visit the whole graph? | MIT6_006S20_lec10.pdf / 3 | Full-BFS and Full-DFS 的循环步骤 | 反复从未访问的顶点启动搜索，直至全部顶点被访问。 |
| D03 | How can I group an undirected network into separate connected islands using graph search? | MIT6_006S20_lec10.pdf / 3 | Graph Connectivity 的证明最后一条 | 执行完整遍历，将每次单源搜索访问的顶点分为一个连通分量。 |
| D04 | My tasks have one-way prerequisites and no cycles. How do DFS finishing times give a valid task order? | MIT6_006S20_lec10.pdf / 4 | Topological Sort 的 Finishing Order 与 Claim | 完整 DFS 的完成顺序反转，得到 DAG 的拓扑序。 |
| D05 | While recursively exploring a directed graph, what sort of edge tells me I've found a cycle? | MIT6_006S20_lec10.pdf / 4 | Cycle Detection，维护当前递归路径祖先的部分 | 指向当前路径上祖先的边表明存在有向环；已访问顶点不一定是祖先。 |
| J01 | Some roads have zero cost and others have negative cost. Which of those is allowed by Dijkstra's assumptions? | MIT6_006S20_lec13.pdf / 1 | Review 最后一条及 Non-negative Edge Weights | 允许零权边；该算法的保证要求边权非负，不能一般性接受负权边。 |
| J02 | I found a cheaper route to a vertex still waiting in Dijkstra's queue. What must I change in the queue? | MIT6_006S20_lec13.pdf / 2 | Dijkstra's Algorithm，松弛步骤之后的队列更新 | 更新距离估计，并降低该顶点在可变优先队列中的键。 |
| J03 | Why is a vertex's distance final when Dijkstra removes it as the current minimum? | MIT6_006S20_lec13.pdf / 3 | Correctness，移除顺序归纳及非负权不等式链 | 安全松弛与非负边权使最小估计在出队时等于真实最短距离。 |
| J04 | Should I use the same priority queue for a very dense graph and a very sparse one? | MIT6_006S20_lec13.pdf / 4 | Running Time 表格下 dense 与 sparse 两条 | 稠密图数组可达 O(V²)；稀疏图二叉堆可达 O(V log V)。 |
| J05 | For Dijkstra's running time, how often do we build the queue, remove a minimum, and lower a key? | MIT6_006S20_lec13.pdf / 4 | Running Time 的 Time/Occurrences 表 | 建队一次，删除最小值 V 次，降低键至多 E 次。 |
| P01 | My recursive Fibonacci function has only two short calls, so why does it get slow so quickly? | MIT6_006S20_lec15.pdf / 2 | Fibonacci Numbers 的代码、递推运行时间及重复子问题 | 同一子问题被重复求解，递归调用树导致指数级工作。 |
| P02 | If I cache recursive answers or fill a table in order, am I solving different Fibonacci subproblems? | MIT6_006S20_lec15.pdf / 3 | Re-using Subproblem Solutions 的 top-down/bottom-up 对照 | 子问题相同；前者按需缓存，后者按依赖拓扑序计算。 |
| P03 | The notes say Fibonacci needs linearly many additions. Is the actual runtime still linear when the integers get huge? | MIT6_006S20_lec15.pdf / 3 | 本页末尾关于整数位数与每次加法代价的三条 | 大整数加法并非常数；按机器字长 w 计，总成本为 O(n+n²/w)。 |
| P04 | What makes dynamic programming different from just splitting a problem into independent recursive pieces? | MIT6_006S20_lec15.pdf / 4 | Dynamic Programming，小节中依赖重叠的条目 | DP 的子问题依赖重叠，复用解；独立分治的依赖通常呈树状。 |
| P05 | In the bowling problem, why isn't the best choice always to hit the first pin immediately? | MIT6_006S20_lec15.pdf / 6（另可接受同文件第 7 页） | Bowling Algorithms，后半部 suffix DP 的三种选择 | 可能跳过、单独击倒或与下一瓶一起击倒；比较各选择的后缀总分。 |

## 原始 PDF

讲师：Erik Demaine、Jason Ku、Justin Solomon。资料归 MIT OpenCourseWare；原始 PDF 保持不变，只在下载时使用下列稳定文件名。

- [Lecture 4: Hashing](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/ce9e94705b914598ce78a00a70a1f734_MIT6_006S20_lec4.pdf) → `MIT6_006S20_lec4.pdf`（5 页，包含末页署名）。
- [Lecture 9: Breadth-First Search](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/196a95604877d326c6586e60477b59d4_MIT6_006S20_lec9.pdf) → `MIT6_006S20_lec9.pdf`（5 页，包含末页署名）。
- [Lecture 10: Depth-First Search](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/f3e349e0eb3288592289d2c81e0c4f4d_MIT6_006S20_lec10.pdf) → `MIT6_006S20_lec10.pdf`（5 页，包含末页署名）。
- [Lecture 13: Dijkstra's Algorithm](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/d819e7f4568aced8d5b59e03db6c7b67_MIT6_006S20_lec13.pdf) → `MIT6_006S20_lec13.pdf`（5 页，包含末页署名）。
- [Lecture 15: Recursive Algorithms](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-spring-2020/9eb3e9a51a7b5b60b0f67c2277f8b0ee_MIT6_006S20_lec15.pdf) → `MIT6_006S20_lec15.pdf`（8 页，包含末页署名）。

短证据锚点用于定位，不足以自动证明一个 chunk 完整回答问题。最终错误分析要对照此表中的段落位置、答案要点和原始 PDF。对不同页的等价证据如需扩充标签，应先人工核对、记录理由并提升数据集版本。
