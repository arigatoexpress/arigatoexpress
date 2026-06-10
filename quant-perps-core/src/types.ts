// Core domain types for the quant-perps execution/risk core.
// Mirrors the well-tested sapphire-perps Python model. Value types are plain
// interfaces + helper functions; behaviour lives in the kernel/broker/router.

export type Side = "long" | "short";
export const sideSign = (s: Side): number => (s === "long" ? 1 : -1);
export const opposite = (s: Side): Side => (s === "long" ? "short" : "long");

export type OrderType = "market" | "limit";
export type TimeInForce = "gtc" | "ioc" | "alo";
export type ExecMode = "paper" | "live";
export type OrderStatus =
  | "pending"
  | "filled"
  | "partially_filled"
  | "rejected"
  | "cancelled";

export interface Quote {
  symbol: string;
  venue: string;
  bid: number;
  ask: number;
  ts?: number;
}
export const mid = (q: Quote): number => (q.bid + q.ask) / 2;
export const spreadBps = (q: Quote): number => {
  const m = mid(q);
  return m <= 0 ? 0 : ((q.ask - q.bid) / m) * 1e4;
};

export interface Order {
  symbol: string;
  side: Side;
  size: number; // always > 0; direction is `side`
  orderType: OrderType;
  limitPrice?: number;
  reduceOnly: boolean;
  tif: TimeInForce;
  venue?: string;
  leverage?: number;
  clientId: string;
  note?: string;
}

let _seq = 0;
const cid = (): string => `o${Date.now().toString(36)}${(_seq++).toString(36)}`;

export function makeOrder(
  p: Partial<Order> & { symbol: string; side: Side; size: number },
): Order {
  const order: Order = {
    orderType: "market",
    reduceOnly: false,
    tif: "gtc",
    clientId: cid(),
    ...p,
  };
  if (order.size <= 0)
    throw new Error("order size must be positive; use `side` for direction");
  if (order.orderType === "limit" && order.limitPrice === undefined)
    throw new Error("limit orders require a limitPrice");
  return order;
}

export const orderSignedSize = (o: Order): number => sideSign(o.side) * o.size;

export interface OrderResult {
  order: Order;
  status: OrderStatus;
  venue: string;
  filledSize: number;
  avgPrice: number;
  venueOrderId?: string;
  reason: string;
}
export const isOk = (r: OrderResult): boolean =>
  r.status === "filled" || r.status === "partially_filled";

export interface Position {
  symbol: string;
  venue: string;
  side: Side;
  size: number; // > 0
  entryPrice: number;
  markPrice: number;
  leverage: number;
}
export const posSignedSize = (p: Position): number => sideSign(p.side) * p.size;
export const posMark = (p: Position): number => p.markPrice || p.entryPrice;
export const posNotional = (p: Position): number => p.size * posMark(p);
export const posUnrealizedPnl = (p: Position): number =>
  sideSign(p.side) * (posMark(p) - p.entryPrice) * p.size;

export interface AccountState {
  venue: string;
  equity: number; // cash + unrealized PnL
  freeCollateral: number;
  positions: Position[];
}
export const positionFor = (
  a: AccountState,
  symbol: string,
): Position | undefined => a.positions.find((p) => p.symbol === symbol);
export const totalNotional = (a: AccountState): number =>
  a.positions.reduce((s, p) => s + posNotional(p), 0);
export const openPositionCount = (a: AccountState): number =>
  a.positions.filter((p) => p.size > 0).length;
