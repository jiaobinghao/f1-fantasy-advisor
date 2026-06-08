1.本地使用的真data数据和模板应该分开，data数据应该ignore
2.使用本仓库的skills，参考now.md内容，给我的fantasy统计数据
3.提醒，如果是赛季的前几场比赛，budget的计算方式有所不同，需要特别注意
4.[fetch_results.py](https://github.com/nachimoreno/F1-APIs/blob/main/Fantasy%20Knapsack%20Solver/src/fetch_results.py)考虑这个的思路，看看可不可以完善我的数据收集方法
5.在一个空目录测试该skills
6.LOCAL_WORKING_NOTES.md是不错的idea，可以把用户提到的信息记录下来，将对这个文件的处理也纳入skills，但是gitignore。记录用户的特殊需求，比如team3“在 Silverstone Sprint、Zandvoort Sprint、Hungary、Singapore Sprint等赛道的备赛时，对team1的建议要提到使用limitless，而且要提醒我，如果当前budget building看上去可以顺利延续到limitless使用后，那就使用limitless，可以兼顾limitless和budget building”，这个样的需求就可以记录在LOCAL_WORKING_NOTES.md里，方便后续参考和调整建议。也要写在readme里让用户指导有这样的功能。
7.我修改了readme中文版，使其更接近用户视角，改动英文版。同时给我一些建议。
8.ok，作为摩纳哥站之后的第一站，给我西班牙加泰罗尼亚赛道的建议吧。初次体验skills