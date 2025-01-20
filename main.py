import os
import argparse

import chess
import chess.engine
import chess.pgn
from tqdm import tqdm


def parse_arguments():
    """
    Parse command-line arguments using argparse and return them.
    """
    parser = argparse.ArgumentParser(description="Chess Opening Tree Generator")
    
    parser.add_argument(
        "--moves",
        type=str,
        nargs="+",
        default=[],
        help="List of moves in SAN notation to reach the starting position.",
    )
    parser.add_argument(
        "--pgn-depth",
        type=int,
        default=5,
        help="Depth of moves to add to the PGN file.",
    )
    parser.add_argument(
        "--engine-depth",
        type=int,
        default=20,
        help="Engine analysis depth.",
    )
    parser.add_argument(
        "--engine-path",
        type=str,
        default=None,
        help="Path to the chess engine. If not provided, uses ENGINE_PATH env var.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output_analysis.pgn",
        help="Output PGN file name.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=1,
        help="Number of CPU threads the engine should use."
    )
    parser.add_argument(
        "--hash-size",
        type=int,
        default=256,  # MB
        help="Hash size in MB for the engine's transposition table."
    )

    return parser.parse_args()


def initialize_pgn_headers():
    """
    Creates and returns a PGN Game object with default headers.
    """
    game = chess.pgn.Game()
    game.headers["Event"] = "Chess Analysis"
    game.headers["Site"] = "*"
    game.headers["Date"] = "*"
    game.headers["Round"] = "*"
    game.headers["White"] = "User"
    game.headers["Black"] = "Engine"
    game.headers["Result"] = "*"
    return game


def estimate_total_moves(pgn_depth, starting_turn):
    """
    Estimate the total number of moves to process for the progress bar.
    
    White uses multipv=1, Black uses multipv=3.
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
    Recursively build a move tree (as a nested list structure) for PGN export.
    White uses multipv=1, Black uses multipv=3.
    """
    if pgn_depth == 0:
        return []

    move_tree = []
    multipv = 1 if position.turn == chess.WHITE else 3

    try:
        analyses = engine.analyse(position, chess.engine.Limit(depth=engine_analysis_depth), multipv=multipv)
    except chess.engine.EngineError as e:
        print(f"Engine error during analysis: {e}")
        exit(1)

    # Engine might return a single dict instead of a list
    if not isinstance(analyses, list):
        analyses = [analyses]

    for analysis in analyses:
        pv = analysis.get('pv')
        if pv:
            board_copy = position.copy()
            legal_pv = []
            for move in pv:
                if board_copy.is_legal(move):
                    legal_pv.append(move)
                    board_copy.push(move)
                else:
                    # If illegal move is found, discard
                    legal_pv = []
                    break

            if legal_pv:
                # First move in the PV
                move = legal_pv[0]
                next_position = position.copy()
                next_position.push(move)

                subsequent_moves = generate_move_tree(
                    next_position, engine, pgn_depth - 1, engine_analysis_depth, progress_bar
                )
                move_tree.append((move, subsequent_moves))

        if progress_bar:
            progress_bar.update(1)

    return move_tree


def add_moves_to_pgn(node, move_tree):
    """
    Recursively adds moves (and their variations) from the move_tree to the PGN node.
    """
    if not move_tree:
        return

    # Main line: the first move in the move_tree
    main_move, main_variations = move_tree[0]
    main_node = node.add_main_variation(main_move)
    add_moves_to_pgn(main_node, main_variations)

    # Any remaining moves are considered variations / side lines
    for move, variations in move_tree[1:]:
        variation_node = node.add_variation(move)
        add_moves_to_pgn(variation_node, variations)


def main():
    """
    Main function: orchestrates argument parsing, engine setup, move-tree generation, and PGN saving.
    """
    # Parse arguments
    args = parse_arguments()

    # Determine engine path from argument or environment variable
    engine_path = args.engine_path or os.getenv("ENGINE_PATH")
    if not engine_path:
        print("ERROR: No engine path provided (via --engine-path or ENGINE_PATH env).")
        exit(1)

    # Read command-line args
    moves = args.moves
    pgn_depth = args.pgn_depth
    engine_analysis_depth = args.engine_depth
    output_file = args.output

    # Engine config
    num_threads = args.threads
    hash_size = args.hash_size

    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path)
    except Exception as e:
        print(f"Failed to start engine at {engine_path}: {e}")
        exit(1)

    engine.configure({
        "Threads": num_threads,
        "Hash": hash_size,
    })

    print(f"Starting engine from '{engine_path}' "
          f"using {num_threads} thread(s) and {hash_size} MB hash size.")

    with engine:
        board = chess.Board()

        # Apply user-specified moves to reach desired starting position
        for move_san in moves:
            try:
                move = board.parse_san(move_san)
                board.push(move)
            except ValueError as e:
                print(f"Invalid move '{move_san}': {e}")
                exit(1)

        game = initialize_pgn_headers()
        node = game

        # Add the initial moves to the PGN
        temp_board = chess.Board()
        for move in board.move_stack:
            node = node.add_main_variation(move)
            temp_board.push(move)

        # Estimate total moves for progress bar
        total_moves = estimate_total_moves(pgn_depth, board.turn)
        progress_bar = tqdm(total=total_moves, desc="Analyzing", unit="move")

        # Generate the move tree from the current position
        move_tree = generate_move_tree(board, engine, pgn_depth, engine_analysis_depth, progress_bar)
        progress_bar.close()

        # Add moves to PGN
        add_moves_to_pgn(node, move_tree)

        # Save PGN file
        try:
            with open(output_file, 'w') as pgn_file:
                exporter = chess.pgn.FileExporter(pgn_file)
                game.accept(exporter)
            print(f"Analysis saved to '{output_file}'")
        except IOError as e:
            print(f"Failed to write PGN file: {e}")
            exit(1)


if __name__ == "__main__":
    main()
