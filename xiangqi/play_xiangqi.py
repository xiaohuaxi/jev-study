"""转发：网页版中国象棋已搬到 games/xiangqi/play_xiangqi.py，这里只为旧命令还能用。参数原样转过去。"""
import pathlib, runpy, sys

NEW = pathlib.Path(__file__).resolve().parent.parent / 'games' / 'xiangqi' / 'play_xiangqi.py'
print('xiangqi/play_xiangqi.py 已搬到 games/xiangqi/play_xiangqi.py，以后请用新路径。', file=sys.stderr)
sys.argv[0] = str(NEW)
sys.path.insert(0, str(NEW.parent))    # 新脚本要 import 同目录的 boards、exp_xiangqi_adapter
runpy.run_path(str(NEW), run_name='__main__')
