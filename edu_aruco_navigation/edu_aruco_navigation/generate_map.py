#!/usr/bin/env python3
import argparse
import csv

def main():
    parser = argparse.ArgumentParser(description="Генератор CSV карты ArUco маркеров.")
    
    # Позиционные аргументы
    parser.add_argument("cx", type=int, help="Количество маркеров по X")
    parser.add_argument("cy", type=int, help="Количество маркеров по Y")
    parser.add_argument("l", type=float, help="Длина стороны маркера (м)")
    parser.add_argument("sx", type=float, help="Расстояние между центрами по X (м)")
    parser.add_argument("sy", type=float, help="Расстояние между центрами по Y (м)")
    
    # Необязательные параметры
    parser.add_argument("-o", "--out", type=str, default="generated_map.csv", help="Имя выходного файла")
    parser.add_argument("-i", "--id", type=int, default=0, help="Начальный ID маркера")
    parser.add_argument("-bl", "--bottom_left", action="store_true",
                        help="Сделать (0,0) в левом нижнем углу (нумерация сверху вниз)")
    parser.add_argument("-rev", "--reverse", action="store_true",
                        help="Записать маркеры в обратном порядке ID")

    args = parser.parse_args()

    total = args.cx * args.cy

    with open(args.out, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['id', 'length', 'x', 'y', 'z'])

        for y_idx in range(args.cy):
            for x_idx in range(args.cx):

                x = x_idx * args.sx
                
                if args.bottom_left:
                    y = (args.cy - 1 - y_idx) * args.sy
                else:
                    y = y_idx * args.sy

                z = 0.0

                index = y_idx * args.cx + x_idx

                if args.reverse:
                    index = total - 1 - index

                current_id = args.id + index

                writer.writerow([
                    current_id,
                    f"{args.l:.4f}",
                    f"{x:.4f}",
                    f"{y:.4f}",
                    f"{z:.4f}"
                ])

    print(f"Сгенерирована карта {args.cx}x{args.cy} ({total} маркеров).")
    if args.bottom_left:
        print("Режим '-bl': Координата (0,0) в левом нижнем углу.")
    if args.reverse:
        print("Режим '-rev': Маркеры записаны в обратном порядке ID.")
    print(f"Файл сохранен как: {args.out}")

if __name__ == "__main__":
    main()