import os
import chess
import chess.engine
import chess.pgn
from tqdm import tqdm

def initialize_pgn_headers():
    """
    Initializes and returns a PGN game.
    """
    game = chess.pgn.Game()
    game.headers["Event"] = "Sample Chess Analysis"
    game.headers["Site"] = "?"
    game.headers["Date"] = "????.??.??"
    game.headers["Round"] = "?"
    game.headers["White"] = "User"
    game.headers["Black"] = "Engine"
    game.headers["Result"] = "*"
    return game

def estimate_total_moves(pgn_depth, starting_turn):
    """
    Estimates the total number of moves to process for the progress bar.
    """
    def count_nodes(depth, turn):
        if depth == 0:
            return 0
        moves = 1 if turn == chess.WHITE else 3
        nodes = moves
        for _ in range(moves):
            nodes += count_nodes(depth - 1, not turn)
        return nodes
    return count_nodes(pgn_depth, starting_turn)

def generate_move_tree(position, engine, pgn_depth, engine_analysis_depth, progress_bar=None):
    """
    Recursive function to build a move tree for PGN export.
    """
    if pgn_depth == 0:
        return []

    move_tree = []

    # Determine multipv based on whose turn it is
    multipv = 1 if position.turn == chess.WHITE else 3

    try:
        # Perform analysis with multipv
        analyses = engine.analyse(position, chess.engine.Limit(depth=engine_analysis_depth), multipv=multipv)
    except chess.engine.EngineError as e:
        print(f"Engine error during analysis: {e}")
        exit(1)

    # Ensure analyses is a list
    if not isinstance(analyses, list):
        analyses = [analyses]

    for analysis in analyses:
        pv = analysis.get('pv')
        if pv:
            # Validate PV moves
            board_copy = position.copy()
            legal_pv = []
            for move in pv:
                if board_copy.is_legal(move):
                    legal_pv.append(move)
                    board_copy.push(move)
                else:
                    # Skip this PV if illegal move is encountered
                    legal_pv = []
                    break

            if legal_pv:
                move = legal_pv[0]
                next_position = position.copy()
                next_position.push(move)
                move_tree.append((
                    move,
                    generate_move_tree(
                        next_position, engine, pgn_depth - 1, engine_analysis_depth, progress_bar
                    )
                ))
        # Update the progress bar
        if progress_bar:
            progress_bar.update(1)

    return move_tree

def add_moves_to_pgn(node, move_tree):
    """
    Recursively adds moves and variations from the move tree to the PGN game.
    """
    if not move_tree:
        return

    main_move, main_variations = move_tree[0]
    main_node = node.add_main_variation(main_move)
    add_moves_to_pgn(main_node, main_variations)

    for move, variations in move_tree[1:]:
        variation_node = node.add_variation(move)
        add_moves_to_pgn(variation_node, variations)

def main():
    # Hardcoded variables
    engine_path = os.getenv('ENGINE_PATH')
    moves = ["d4", "d5", "c4", "e6"]  # List of moves in SAN notation to reach the starting position
    pgn_depth = 16  # Depth of moves to add to the PGN file
    engine_analysis_depth = 30  # Depth Stockfish should analyze for each move
    output_file = "output_analysis.pgn"

    # Configure the number of threads and hash size
    num_threads = 18  # Set this to the number of CPU cores you want to use
    hash_size = 65536 # Hash size in MB (adjust based on your system's RAM)

    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    except Exception as e:
        print(f"Failed to start engine: {e}")
        exit(1)

    # Configure the engine with additional options
    engine.configure({
        "Threads": num_threads,
        "Hash": hash_size,
    })

    with engine:
        # Initialize the board
        board = chess.Board()
        for move_san in moves:
            try:
                move = board.parse_san(move_san)
                board.push(move)
            except ValueError as e:
                print(f"Invalid move '{move_san}': {e}")
                exit(1)

        # Initialize PGN game
        game = initialize_pgn_headers()
        node = game

        # Add initial moves to PGN
        temp_board = chess.Board()
        for move in board.move_stack:
            node = node.add_main_variation(move)
            temp_board.push(move)

        # Estimate total moves for progress bar
        total_moves = estimate_total_moves(pgn_depth, board.turn)
        progress_bar = tqdm(total=total_moves, desc="Analyzing", unit="move")

        # Generate move tree
        move_tree = generate_move_tree(board, engine, pgn_depth, engine_analysis_depth, progress_bar)
        progress_bar.close()

        # Add moves to PGN
        add_moves_to_pgn(node, move_tree)

        # Save PGN file
        try:
            with open(output_file, 'w') as pgn_file:
                exporter = chess.pgn.FileExporter(pgn_file)
                game.accept(exporter)
            print(f"Analysis saved to {output_file}")
        except IOError as e:
            print(f"Failed to write PGN file: {e}")
            exit(1)

if __name__ == '__main__':
    main()
