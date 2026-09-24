"""转发：网页版国际象棋已搬到 games/chess/play_chess.py，这里只为旧命令还能用。参数原样转过去。"""
import pathlib, runpy, sys

NEW = pathlib.Path(__file__).resolve().parent / 'chess' / 'play_chess.py'
print('games/play_chess.py 已搬到 games/chess/play_chess.py，以后请用新路径。', file=sys.stderr)
sys.argv[0] = str(NEW)
sys.path.insert(0, str(NEW.parent))
runpy.run_path(str(NEW), run_name='__main__')
