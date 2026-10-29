/**
 * BLOCK-STRUCTURE ENGINE — a dependency-free transcription of CommonMark
 * 0.31.2's block parser.
 *
 * WHY THIS EXISTS. The structure behind `lineStructure` was hand-written as a
 * container/leaf state machine. Six consecutive reviews each found a real defect
 * in the SAME continuation rule (A23, A24, A28, A29, A30, A31/A32, A33), because
 * the file held TWO competing continuation implementations — one that retained
 * the whole active stack on a container-relative blank, and a second path for
 * fences/HTML whose list-width test lacked the reference item's
 * blank-before-indent branch. Patching the sixth did not close the family. This
 * module replaces the model wholesale: it transcribes the reference algorithm so
 * there is exactly ONE continuation operation per block, evaluated at each
 * block's CURRENT offset with blankness recomputed from the parse state.
 *
 * PROVENANCE. Transcribed from commonmark.js 0.31.2 `lib/blocks.js` and the
 * block-relevant helpers of `lib/inlines.js` (reference-label parsing used only
 * to decide whether a paragraph's leading text is a link reference definition —
 * a fact that changes whether the paragraph exists and which lines it owns).
 * Only the block-level algorithm is transcribed: inline parsing, rendering, and
 * the destination/title VALUES of reference definitions are omitted, because
 * none of them change block ownership. No `commonmark` module is imported at
 * runtime.
 *
 * REV66-P3 - BSD-2-Clause requires the copyright notice, conditions and
 * disclaimer to be retained with source redistribution. The repository has no
 * separate LICENSE file, so the notice is reproduced here in full:
 *
 *   commonmark.js
 *   Copyright (c) 2014, John MacFarlane
 *   All rights reserved.
 *
 *   Redistribution and use in source and binary forms, with or without
 *   modification, are permitted provided that the following conditions are met:
 *
 *       * Redistributions of source code must retain the above copyright
 *         notice, this list of conditions and the following disclaimer.
 *
 *       * Redistributions in binary form must reproduce the above
 *         copyright notice, this list of conditions and the following
 *         disclaimer in the documentation and/or other materials provided
 *         with the distribution.
 *
 *   THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
 *   "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
 *   LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
 *   A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
 *   OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
 *   SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
 *   LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
 *   DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
 *   THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
 *   (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
 *   OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 * THE REFERENCE'S MODEL, IN ONE PARAGRAPH. A line is incorporated by walking the
 * open-block chain from the document downward. Each open block's `continue`
 * returns MATCHED (0), UNMATCHED (1), or LINE-CONSUMED (2). The walk stops at
 * the FIRST failure: `container` backs up to the last matching block and every
 * unmatched descendant is closed (`closeUnmatchedBlocks`). The surviving level
 * is then offered the line as a sequence of block STARTS (block quote, ATX
 * heading, fence, HTML, setext, thematic break, list item, indented code) in the
 * reference's order; a container start keeps the loop going, a leaf start ends
 * it. What remains at the parser offset is text: a lazy paragraph continuation
 * when an as-yet-unclosed paragraph still tips the stack, otherwise a new
 * paragraph (or content appended to the accepting leaf). Blankness is recomputed
 * by `findNextNonspace` from the CURRENT offset on every block, never once per
 * line. This single loop is the whole continuation semantics.
 *
 * WHAT WE READ OFF THE PARSE. `lineStructure` consumes the finalized block tree
 * and reports, per input line: the fence membership (`changes` / `inside`) and
 * the two ownership facts consumers need (`topLevel`, `paragraphStart`). It never
 * re-derives containers from strings, so the marker, counting, and question
 * surfaces cannot drift apart again.
 */

export type BlockType =
  | "document"
  | "block_quote"
  | "list"
  | "item"
  | "paragraph"
  | "heading"
  | "thematic_break"
  | "code_block"
  | "html_block";

/** One node of the parsed block tree. Mirrors the reference `Node` subset. */
export interface BlockNode {
  type: BlockType;
  parent: BlockNode | null;
  firstChild: BlockNode | null;
  lastChild: BlockNode | null;
  prev: BlockNode | null;
  next: BlockNode | null;
  /** [startLine, startCol] .. [endLine, endCol], 1-based like the reference. */
  sourcepos: [[number, number], [number, number]];
  open: boolean;
  stringContent: string | null;
  /** Fenced code block bookkeeping (the reference's `_isFenced` family). */
  isFenced: boolean;
  fenceChar: string;
  fenceLength: number;
  fenceOffset: number;
  /** HTML block type 1-7. */
  htmlBlockType: number;
  /** List data (`_listData` in the reference): type, start, delimiter, padding. */
  listData: {
    type: string | null;
    tight: boolean;
    bulletChar: string | null;
    start: number | null;
    delimiter: string | null;
    padding: number | null;
    markerOffset: number;
  };
}

/** Allocate a fresh block node, exactly as the reference `Node` does. */
function makeBlock(type: BlockType, sourcepos: [[number, number], [number, number]]): BlockNode {
  return {
    type,
    parent: null,
    firstChild: null,
    lastChild: null,
    prev: null,
    next: null,
    sourcepos,
    open: true,
    stringContent: null,
    isFenced: false,
    fenceChar: "",
    fenceLength: 0,
    fenceOffset: 0,
    htmlBlockType: 0,
    listData: {
      type: null,
      tight: true,
      bulletChar: null,
      start: null,
      delimiter: null,
      padding: null,
      markerOffset: 0,
    },
  };
}

/** Detach a node from its parent and siblings (reference `unlink`). */
function unlinkBlock(node: BlockNode): void {
  if (node.prev !== null) {
    node.prev.next = node.next;
  } else if (node.parent !== null) {
    node.parent.firstChild = node.next;
  }
  if (node.next !== null) {
    node.next.prev = node.prev;
  } else if (node.parent !== null) {
    node.parent.lastChild = node.prev;
  }
  node.parent = null;
  node.next = null;
  node.prev = null;
}

/** Append a child to a parent (reference `appendChild`). */
function appendChild(parent: BlockNode, child: BlockNode): void {
  unlinkBlock(child);
  child.parent = parent;
  if (parent.lastChild !== null) {
    parent.lastChild.next = child;
    child.prev = parent.lastChild;
    parent.lastChild = child;
  } else {
    parent.firstChild = child;
    parent.lastChild = child;
  }
}

/** Insert `sibling` directly after `node` (reference `insertAfter`). */
function insertAfter(node: BlockNode, sibling: BlockNode): void {
  unlinkBlock(sibling);
  sibling.next = node.next;
  if (sibling.next !== null) sibling.next.prev = sibling;
  sibling.prev = node;
  node.next = sibling;
  sibling.parent = node.parent;
  if (sibling.next === null && sibling.parent !== null) {
    sibling.parent.lastChild = sibling;
  }
}

/** The CommonMark "accepts lines" predicate (canContain is false for leaves). */
function acceptsLines(type: BlockType): boolean {
  return type === "code_block" || type === "html_block" || type === "paragraph";
}

/** CommonMark `canContain`: whether a block of `type` may contain `child`. */
function canContain(type: BlockType, child: BlockType): boolean {
  switch (type) {
    case "document":
    case "block_quote":
    case "item":
      return child !== "item";
    case "list":
      return child === "item";
    default:
      return false;
  }
}

const CODE_INDENT = 4;

// --- the reference's block-level regular expressions -----------------------
// The HTML tag grammar (common.js OPENTAG/CLOSETAG). Built with `new RegExp`
// rather than a literal because the type-7 alternation below is long enough that
// the type-stripping loader misreads the literal as a division/JSX token.
const HTML_TAGNAME = "[A-Za-z][A-Za-z0-9-]*";
const HTML_ATTRIBUTENAME = "[a-zA-Z_:][a-zA-Z0-9:._-]*";
const HTML_UNQUOTEDVALUE = "[^\"'=<>`\\x00-\\x20]+";
const HTML_ATTRIBUTEVALUE =
  "(?:" + HTML_UNQUOTEDVALUE + "|'[^']*'|\"[^\"]*\")";
const HTML_ATTRIBUTEVALUESPEC = "(?:\\s*=\\s*" + HTML_ATTRIBUTEVALUE + ")";
const HTML_ATTRIBUTE = "(?:\\s+" + HTML_ATTRIBUTENAME + HTML_ATTRIBUTEVALUESPEC + "?)";
const HTML_OPENTAG = "<" + HTML_TAGNAME + HTML_ATTRIBUTE + "*\\s*/?>";
const HTML_CLOSETAG = "</" + HTML_TAGNAME + "\\s*[>]";

const reHtmlBlockOpen: (RegExp | null)[] = [
  null,
  /^<(?:script|pre|textarea|style)(?:\s|>|$)/i,
  /^<!--/,
  /^<[?]/,
  /^<![A-Za-z]/,
  /^<!\[CDATA\[/,
  /^<[/]?(?:address|article|aside|base|basefont|blockquote|body|caption|center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|footer|form|frame|frameset|h[123456]|head|header|hr|html|iframe|legend|li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|section|search|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)(?:\s|[/]?[>]|$)/i,
  // type 7 is checked separately below (it needs the paragraph "maybe lazy"
  // guard the reference applies at the call site).
  new RegExp("^(?:" + HTML_OPENTAG + "|" + HTML_CLOSETAG + ")\\s*$", "i"),
];

const reHtmlBlockClose: (RegExp | null)[] = [
  null,
  /<\/(?:script|pre|textarea|style)>/i,
  /-->/,
  /\?>/,
  />/,
  /\]\]>/,
];

const reThematicBreak = /^(?:\*[ \t]*){3,}$|^(?:_[ \t]*){3,}$|^(?:-[ \t]*){3,}$/;
const reMaybeSpecial = /^[#`~*+_=<>0-9-]/;
const reNonSpace = /[^ \t\f\v\r\n]/;
const reBulletListMarker = /^[*+-]/;
const reOrderedListMarker = /^(\d{1,9})([.)])/;
const reATXHeadingMarker = /^#{1,6}(?:[ \t]+|$)/;
const reCodeFence = /^`{3,}(?!.*`)|^~{3,}/;
const reClosingCodeFence = /^(?:`{3,}|~{3,})(?=[ \t]*$)/;
const reSetextHeadingLine = /^(?:=+|-+)[ \t]*$/;
const reLineEnding = /\r\n|\n|\r/;

/**
 * True when a string contains only Markdown blank characters.
 *
 * Markdown blankness is NOT JavaScript `String.prototype.trim()`: `trim()`
 * strips the whole Unicode whitespace class, including U+00A0 NO-BREAK SPACE and
 * other non-ASCII spaces that Markdown treats as ORDINARY PARAGRAPH CONTENT. A
 * line holding only an NBSP is therefore NOT blank - it continues the open
 * paragraph - but a `trim()`-based test read it as blank, ended the paragraph,
 * and promoted the declaration beneath it to document level (DEFECT F8, the
 * harmful false positive). `isBlank` is the reference's own predicate for this
 * question and the single blankness rule the whole walk uses.
 */
function isBlank(s: string): boolean {
  return !reNonSpace.test(s);
}

/** True for space/tab (the reference `isSpaceOrTab`). */
function isSpaceOrTab(c: number): boolean {
  return c === 32 || c === 9;
}

/** Character code at `pos`, or -1 past the end (reference `peek`). */
function peekChar(ln: string, pos: number): number {
  return pos < ln.length ? ln.charCodeAt(pos) : -1;
}

// --- reference-definition recognition (block ownership only) ----------------
//
// A paragraph's leading text may be one or more link reference definitions
// (CommonMark 4.7). If every line of the paragraph is consumed that way, the
// paragraph does not exist; the lines it absorbed are NOT a document paragraph,
// which changes the ownership answer for anything beneath them. We therefore
// transcribe `parseReference`'s CONSUMPTION logic. The destination/title values
// are discarded: they never affect which block owns a line.

const reLinkLabel = /^\[(?:[^\\[\]]|\\.){0,1000}\]/s;
const reLinkDestinationBraces = /^(?:<(?:[^<>\n\\\x00]|\\.)*>)/;
const ESCAPABLE = "[!\"#$%&'()*+,./:;<=>?@[\\\\\\]^_`{|}~-]";
// REV66-P2: the reference builds the title body from ESCAPED_CHAR (a BACKSLASH
// followed by an escapable character) - NOT from bare ESCAPABLE. Substituting
// ESCAPABLE let a raw delimiter character occur inside its own title, so
// `[a]: /x "t" junk "u"` was greedily read as ONE title `"t" junk "u"` and the
// definition was consumed, when the reference rejects it (the valid short title
// `"t"` is followed by non-whitespace) and keeps the paragraph alive.
const ESCAPED_CHAR = "\\\\" + ESCAPABLE;
const reEscapable = new RegExp("^" + ESCAPABLE);
// Verbatim transcription of the reference's reLinkTitle body. Each of the three
// delimiter forms is built as:
//
//     ESCAPED_CHAR | '\\[^\\]' | '[^\\<delim>\\x00]'
//
// The second alternative is written in the reference as the SINGLE-quoted JS
// literal '\\[^\\]', which decodes to the four-character regex source \[^\] -
// i.e. a LITERAL BACKSLASH followed by any NON-BACKSLASH. Both halves of that
// decoding matter, and a previous revision got both wrong (REV67-P1): as a
// double-quoted "\\\\[^\\\\]" it decoded to \\[^\\] (two backslashes = an
// escaped-backslash regex, matching one backslash, then a class that still
// admitted a backslash), and the ordinary classes below were written with two
// backslashes where the reference has four. The result excluded the delimiter
// but NOT a literal backslash, so the regex could backtrack - consuming a
// backslash via the permissive ordinary alternative and then closing the title
// on an ESCAPED delimiter. Input `[a]: /x "t\"` therefore wrongly consumed the
// definition (emptied-setext path -> paragraph continues -> `unknown`) where the
// reference keeps it as heading text and yields `continue`.
//
// Built from concatenation so the JS escaping is auditable against the
// reference source rather than hidden in one literal.
const ESC_BACKSLASH = "\\\\"; // regex source: a single literal backslash
const ESC_NONBACKSLASH = "[^\\\\]"; // regex source: any NON-backslash char
const ANY_ESCAPE = ESC_BACKSLASH + ESC_NONBACKSLASH; // regex source: \[^\]
const classExcluding = (chars: string) => "[^" + ESC_BACKSLASH + chars + "\\x00]";
const reLinkTitle = new RegExp(
  '^(?:"(' +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding('"') +
    ')*"' +
    "|" +
    "'(" +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding("'") +
    ")*'" +
    "|" +
    "\\(" +
    "(" +
    ESCAPED_CHAR +
    "|" +
    ANY_ESCAPE +
    "|" +
    classExcluding("()") +
    ")*\\)" +
    ")",
);
const reSpnl = /^ *(?:\n *)?/;
const reSpaceAtEndOfLine = /^ *(?:\n|$)/;
const reWhitespaceChar = /^[ \t\n\x0b\x0c\x0d]/;

/** Convert a code point to its string, dependency-free. */
function fromCodePoint(code: number): string {
  return String.fromCodePoint(code);
}

/** The subject/position scanner `parseReference` needs. */
interface RefScanner {
  subject: string;
  pos: number;
}

function refMatch(sc: RefScanner, re: RegExp): string | null {
  const m = re.exec(sc.subject.slice(sc.pos));
  if (m === null) return null;
  sc.pos += m.index + m[0].length;
  return m[0];
}

function refPeek(sc: RefScanner): number {
  return sc.pos < sc.subject.length ? sc.subject.charCodeAt(sc.pos) : -1;
}

function refParseLinkLabel(sc: RefScanner): number {
  const m = refMatch(sc, reLinkLabel);
  if (m === null || m.length > 1001) return 0;
  return m.length;
}

function refParseLinkDestination(sc: RefScanner): string | null {
  let res = refMatch(sc, reLinkDestinationBraces);
  if (res === null) {
    if (refPeek(sc) === 60 /* < */) return null;
    const savepos = sc.pos;
    let openparens = 0;
    let c = refPeek(sc);
    while (c !== -1) {
      if (c === 92 /* \ */ && reEscapable.test(sc.subject.charAt(sc.pos + 1))) {
        sc.pos += 1;
        if (refPeek(sc) !== -1) sc.pos += 1;
      } else if (c === 40 /* ( */) {
        sc.pos += 1;
        openparens += 1;
      } else if (c === 41 /* ) */) {
        if (openparens < 1) break;
        sc.pos += 1;
        openparens -= 1;
      } else if (reWhitespaceChar.exec(fromCodePoint(c)) !== null) {
        break;
      } else {
        sc.pos += 1;
      }
      c = refPeek(sc);
    }
    if (sc.pos === savepos && c !== 41) return null;
    if (openparens !== 0) return null;
    res = sc.subject.slice(savepos, sc.pos);
    return res;
  }
  return res;
}

function refParseLinkTitle(sc: RefScanner): string | null {
  const title = refMatch(sc, reLinkTitle);
  return title === null ? null : title.slice(1, -1);
}

function normalizeReference(str: string): string {
  return str.slice(1, str.length - 1).trim().replace(/[ \t\r\n]+/g, " ").toLowerCase().toUpperCase();
}

/**
 * Consume one leading link reference definition from `s`, returning the number
 * of characters consumed (0 when `s` does not begin with one).
 */
function parseReferenceDefinition(s: string): number {
  const sc: RefScanner = { subject: s, pos: 0 };
  const startpos = sc.pos;
  const matchChars = refParseLinkLabel(sc);
  if (matchChars === 0) return 0;
  const rawlabel = sc.subject.slice(0, matchChars);
  if (refPeek(sc) === 58 /* : */) {
    sc.pos += 1;
  } else {
    return 0;
  }
  refMatch(sc, reSpnl);
  if (refParseLinkDestination(sc) === null) return 0;
  const beforetitle = sc.pos;
  refMatch(sc, reSpnl);
  let title: string | null = null;
  if (sc.pos !== beforetitle) title = refParseLinkTitle(sc);
  if (title === null) sc.pos = beforetitle;
  let atLineEnd = true;
  if (refMatch(sc, reSpaceAtEndOfLine) === null) {
    if (title === null) {
      atLineEnd = false;
    } else {
      title = null;
      sc.pos = beforetitle;
      atLineEnd = refMatch(sc, reSpaceAtEndOfLine) !== null;
    }
  }
  if (!atLineEnd) return 0;
  if (normalizeReference(rawlabel) === "") return 0;
  return sc.pos - startpos;
}

/**
 * Strip leading link reference definitions from `content`, returning the
 * remainder, exactly as the reference does at paragraph finalize / setext time.
 */
function stripReferenceDefinitions(content: string): string {
  let rest = content;
  while (rest.length > 0 && rest.charCodeAt(0) === 91 /* [ */) {
    const consumed = parseReferenceDefinition(rest);
    if (consumed === 0) break;
    rest = rest.slice(consumed);
  }
  return rest;
}

// --- parser state ----------------------------------------------------------
interface BlockParser {
  doc: BlockNode;
  tip: BlockNode;
  oldtip: BlockNode;
  currentLine: string;
  lineNumber: number;
  offset: number;
  column: number;
  nextNonspace: number;
  nextNonspaceColumn: number;
  indent: number;
  indented: boolean;
  blank: boolean;
  partiallyConsumedTab: boolean;
  allClosed: boolean;
  lastMatchedContainer: BlockNode;
  refmap: Record<string, { destination: string; title: string }>;
  lastLineLength: number;
  /** Trace recorded while incorporating lines (0-based line index keys). */
  trace: {
    /** True when this line created a fresh paragraph (its first content line). */
    paragraphStarted: boolean[];
    /** One entry per FENCED code block, in opener order. */
    fences: { open: number; end: number; closerLine: number | null }[];
    /** Set while a fenced closer is being finalized, so the fence records its closer. */
    closingFence: boolean;
  };
}

function makeParser(): BlockParser {
  const doc = makeBlock("document", [
    [1, 1],
    [0, 0],
  ]);
  return {
    doc,
    tip: doc,
    oldtip: doc,
    currentLine: "",
    lineNumber: 0,
    offset: 0,
    column: 0,
    nextNonspace: 0,
    nextNonspaceColumn: 0,
    indent: 0,
    indented: false,
    blank: false,
    partiallyConsumedTab: false,
    allClosed: true,
    lastMatchedContainer: doc,
    refmap: {},
    lastLineLength: 0,
    trace: { paragraphStarted: [], fences: [], closingFence: false },
  };
}

/** Reference `advanceOffset`, including the partially-consumed-tab rule. */
function advanceOffset(p: BlockParser, count: number, columns: boolean): void {
  const currentLine = p.currentLine;
  let charsToTab: number;
  let charsToAdvance: number;
  let c: string;
  while (count > 0 && (c = currentLine[p.offset])) {
    if (c === "\t") {
      charsToTab = 4 - (p.column % 4);
      if (columns) {
        p.partiallyConsumedTab = charsToTab > count;
        charsToAdvance = charsToTab > count ? count : charsToTab;
        p.column += charsToAdvance;
        p.offset += p.partiallyConsumedTab ? 0 : 1;
        count -= charsToAdvance;
      } else {
        p.partiallyConsumedTab = false;
        p.column += charsToTab;
        p.offset += 1;
        count -= 1;
      }
    } else {
      p.partiallyConsumedTab = false;
      p.offset += 1;
      p.column += 1;
      count -= 1;
    }
  }
}

function advanceNextNonspace(p: BlockParser): void {
  p.offset = p.nextNonspace;
  p.column = p.nextNonspaceColumn;
  p.partiallyConsumedTab = false;
}

/** Reference `findNextNonspace`: recomputes blankness at the current offset. */
function findNextNonspace(p: BlockParser): void {
  const currentLine = p.currentLine;
  let i = p.offset;
  let cols = p.column;
  let c: string;
  while ((c = currentLine.charAt(i)) !== "") {
    if (c === " ") {
      i++;
      cols++;
    } else if (c === "\t") {
      i++;
      cols += 4 - (cols % 4);
    } else {
      break;
    }
  }
  p.blank = c === "\n" || c === "\r" || c === "";
  p.nextNonspace = i;
  p.nextNonspaceColumn = cols;
  p.indent = p.nextNonspaceColumn - p.column;
  p.indented = p.indent >= CODE_INDENT;
}

/** Reference `addLine`: append the current line's tail to the tip's content. */
function addLine(p: BlockParser): void {
  if (p.tip.stringContent === null) p.tip.stringContent = "";
  if (p.partiallyConsumedTab) {
    p.offset += 1;
    const charsToTab = 4 - (p.column % 4);
    p.tip.stringContent += " ".repeat(charsToTab);
  }
  p.tip.stringContent += p.currentLine.slice(p.offset) + "\n";
}

/** Reference `addChild`: descend to a block that can contain `tag`, then add. */
function addChild(p: BlockParser, tag: BlockType, offset: number): BlockNode {
  while (!canContain(p.tip.type, tag)) {
    finalizeBlock(p, p.tip, p.lineNumber - 1);
  }
  const columnNumber = offset + 1;
  const newBlock = makeBlock(tag, [
    [p.lineNumber, columnNumber],
    [0, 0],
  ]);
  newBlock.stringContent = "";
  appendChild(p.tip, newBlock);
  p.tip = newBlock;
  return newBlock;
}

/** Reference `finalize`: close a block and run its type-specific finalizer. */
function finalizeBlock(p: BlockParser, block: BlockNode, lineNumber: number): void {
  const above = block.parent;
  block.open = false;
  block.sourcepos[1] = [lineNumber, p.lastLineLength];
  switch (block.type) {
    case "document":
      removeLinkReferenceDefinitions(p, block);
      break;
    case "list": {
      let item = block.firstChild;
      while (item !== null) {
        if (item.next !== null && endsWithBlankLine(item)) {
          block.listData.tight = false;
          break;
        }
        let subitem = item.firstChild;
        while (subitem !== null) {
          if (subitem.next !== null && endsWithBlankLine(subitem)) {
            block.listData.tight = false;
            break;
          }
          subitem = subitem.next;
        }
        item = item.next;
      }
      if (block.lastChild !== null) block.sourcepos[1] = block.lastChild.sourcepos[1];
      break;
    }
    case "item":
      if (block.lastChild !== null) {
        block.sourcepos[1] = block.lastChild.sourcepos[1];
      } else {
        block.sourcepos[1][0] = block.sourcepos[0][0];
        block.sourcepos[1][1] =
          block.listData.markerOffset + (block.listData.padding ?? 0);
      }
      break;
    case "code_block":
      if (block.isFenced) {
        // Record the fence's CONTENT range for `inside`. A fence closed by a
        // closer ends on the line BEFORE that closer; a fence ended by its
        // container (or EOF) ends on its last content line, which finalize has
        // already recorded as `sourcepos[1][0]`.
        const closerLine = p.trace.closingFence ? block.sourcepos[1][0] : null;
        p.trace.closingFence = false;
        p.trace.fences.push({
          open: block.sourcepos[0][0],
          end: closerLine === null ? block.sourcepos[1][0] : closerLine - 1,
          closerLine,
        });
        block.stringContent = null;
      } else {
        const lines = (block.stringContent ?? "").split("\n");
        while (/^[ \t]*$/.test(lines[lines.length - 1])) lines.pop();
        block.sourcepos[1][0] = block.sourcepos[0][0] + lines.length - 1;
        block.sourcepos[1][1] = block.sourcepos[0][1] + (lines[lines.length - 1] ?? "").length - 1;
        block.stringContent = null;
      }
      break;
    case "html_block":
      block.stringContent = null;
      break;
    default:
      break;
  }
  p.tip = above ?? p.doc; // document's parent is null; `lineStructure` stops there
}

/** Reference `endsWithBlankLine`: does `block` end on a line before its next? */
function endsWithBlankLine(block: BlockNode): boolean {
  return (
    block.next !== null &&
    block.sourcepos[1][0] !== block.next.sourcepos[0][0] - 1
  );
}

/** Reference `closeUnmatchedBlocks`: close every block past the last match. */
function closeUnmatchedBlocks(p: BlockParser): void {
  if (!p.allClosed) {
    while (p.oldtip !== p.lastMatchedContainer) {
      const parent = p.oldtip.parent;
      finalizeBlock(p, p.oldtip, p.lineNumber - 1);
      p.oldtip = parent ?? p.doc;
    }
    p.allClosed = true;
  }
}

/**
 * Reference `removeLinkReferenceDefinitions`: strip leading reference
 * definitions from every paragraph; unlink paragraphs left empty. A removed
 * paragraph no longer owns its lines, so ownership must read the tree AFTER
 * this runs.
 */
function removeLinkReferenceDefinitions(p: BlockParser, tree: BlockNode): void {
  const emptyNodes: BlockNode[] = [];
  walkBlocks(tree, (node, entering) => {
    if (!entering || node.type !== "paragraph") return;
    let content = node.stringContent ?? "";
    let hasReferenceDefs = false;
    while (content.length > 0 && content.charCodeAt(0) === 91 /* [ */) {
      const consumed = parseReferenceDefinition(content);
      if (consumed === 0) break;
      const removedText = content.slice(0, consumed);
      content = content.slice(consumed);
      hasReferenceDefs = true;
      node.sourcepos[0][0] += removedText.split("\n").length - 1;
    }
    node.stringContent = content;
    if (hasReferenceDefs && isBlank(content)) emptyNodes.push(node);
  });
  for (const node of emptyNodes) unlinkBlock(node);
}

/**
 * Pre-order block walk with an entering/exiting flag.
 *
 * ITERATIVE, with an explicit stack. The block tree's depth is bounded only by
 * the input's nesting, and a recursive walk consumed one JavaScript stack frame
 * per level: a deeply nested message (thousands of `> ` levels) overflowed the
 * finite call stack with `RangeError: Maximum call stack size exceeded` before
 * marker extraction returned. That threw out of `readDeclaredMarker`, out of
 * `handleBeforeSettle`, and out of the settlement path, so a genuine printed
 * CONTINUE stopped silently with no bridge and no notice. The traversal must
 * therefore never depend on the host's call-stack depth.
 *
 * Order is preserved EXACTLY as the former recursion emitted it: `visit(node,
 * true)` pre-order, then each child in `firstChild..next` order, then
 * `visit(node, false)`. A frame's exit is scheduled BEFORE its children are
 * pushed, and the children are pushed in REVERSE so they pop forward, keeping
 * the entering/exiting sequence identical for every consumer.
 */
function walkBlocks(
  root: BlockNode,
  visit: (node: BlockNode, entering: boolean) => void,
): void {
  // `entering` distinguishes the two passes over a frame. Children are gathered
  // into a reusable scratch array only to reverse them; no recursion, no
  // host-stack use regardless of nesting depth.
  const stack: Array<{ node: BlockNode; entering: boolean }> = [
    { node: root, entering: true },
  ];
  while (stack.length > 0) {
    const frame = stack.pop() as { node: BlockNode; entering: boolean };
    const node = frame.node;
    if (frame.entering) {
      visit(node, true);
      // Schedule this node's exit to run AFTER every descendant.
      stack.push({ node, entering: false });
      const children: BlockNode[] = [];
      for (let child = node.firstChild; child !== null; child = child.next) {
        children.push(child);
      }
      for (let i = children.length - 1; i >= 0; i -= 1) {
        stack.push({ node: children[i], entering: true });
      }
    } else {
      visit(node, false);
    }
  }
}

/** Reference `parseListMarker`: returns marker data, or null. */
function parseListMarker(p: BlockParser, container: BlockNode): BlockNode["listData"] | null {
  const rest = p.currentLine.slice(p.nextNonspace);
  let match: RegExpMatchArray | null;
  let nextc: number;
  let spacesStartCol: number;
  let spacesStartOffset: number;
  const data = {
    type: null as string | null,
    tight: true,
    bulletChar: null as string | null,
    start: null as number | null,
    delimiter: null as string | null,
    padding: null as number | null,
    markerOffset: p.indent,
  };
  if (p.indent >= 4) return null;
  if ((match = rest.match(reBulletListMarker))) {
    data.type = "bullet";
    data.bulletChar = match[0][0];
  } else if (
    (match = rest.match(reOrderedListMarker)) &&
    (container.type !== "paragraph" || parseInt(match[1] ?? "0", 10) === 1)
  ) {
    data.type = "ordered";
    data.start = parseInt(match[1] ?? "0", 10);
    data.delimiter = match[2] ?? "";
  } else {
    return null;
  }
  nextc = peekChar(p.currentLine, p.nextNonspace + match[0].length);
  if (!(nextc === -1 || nextc === 9 || nextc === 32)) return null;
  if (
    container.type === "paragraph" &&
    !reNonSpace.test(p.currentLine.slice(p.nextNonspace + match[0].length))
  ) {
    return null;
  }
  advanceNextNonspace(p);
  advanceOffset(p, match[0].length, true);
  spacesStartCol = p.column;
  spacesStartOffset = p.offset;
  do {
    advanceOffset(p, 1, true);
    nextc = peekChar(p.currentLine, p.offset);
  } while (p.column - spacesStartCol < 5 && isSpaceOrTab(nextc));
  const blankItem = peekChar(p.currentLine, p.offset) === -1;
  const spacesAfterMarker = p.column - spacesStartCol;
  if (spacesAfterMarker >= 5 || spacesAfterMarker < 1 || blankItem) {
    data.padding = match[0].length + 1;
    p.column = spacesStartCol;
    p.offset = spacesStartOffset;
    if (isSpaceOrTab(peekChar(p.currentLine, p.offset))) {
      advanceOffset(p, 1, true);
    }
  } else {
    data.padding = match[0].length + spacesAfterMarker;
  }
  return data;
}

/** Reference `listsMatch`: do two list data records agglomerate? */
function listsMatch(listData: BlockNode["listData"], itemData: BlockNode["listData"]): boolean {
  return (
    listData.type === itemData.type &&
    listData.delimiter === itemData.delimiter &&
    listData.bulletChar === itemData.bulletChar
  );
}

/**
 * Run the block `continue` for one open block. Returns MATCHED (0),
 * UNMATCHED (1), or LINE-CONSUMED (2). This is the ONE continuation operation:
 * each block answers for its CURRENT offset, and the caller stops at the first
 * non-zero.
 */
function continueBlock(p: BlockParser, container: BlockNode): number {
  switch (container.type) {
    case "document":
      return 0;
    case "list":
      return 0;
    case "block_quote": {
      const ln = p.currentLine;
      if (!p.indented && peekChar(ln, p.nextNonspace) === 62 /* > */) {
        advanceNextNonspace(p);
        advanceOffset(p, 1, false);
        if (isSpaceOrTab(peekChar(ln, p.offset))) advanceOffset(p, 1, true);
        return 0;
      }
      return 1;
    }
    case "item": {
      if (p.blank) {
        if (container.firstChild === null) {
          return 1;
        }
        advanceNextNonspace(p);
      } else if (
        p.indent >=
        container.listData.markerOffset + (container.listData.padding ?? 0)
      ) {
        advanceOffset(
          p,
          container.listData.markerOffset + (container.listData.padding ?? 0),
          true,
        );
      } else {
        return 1;
      }
      return 0;
    }
    case "heading":
    case "thematic_break":
      return 1;
    case "code_block": {
      const ln = p.currentLine;
      const indent = p.indent;
      if (container.isFenced) {
        const match =
          indent <= 3 &&
          ln.charAt(p.nextNonspace) === container.fenceChar &&
          ln.slice(p.nextNonspace).match(reClosingCodeFence);
        if (match && match[0].length >= container.fenceLength) {
          p.lastLineLength = p.offset + indent + match[0].length;
          p.trace.closingFence = true;
          finalizeBlock(p, container, p.lineNumber);
          return 2;
        }
        let i = container.fenceOffset;
        while (i > 0 && isSpaceOrTab(peekChar(ln, p.offset))) {
          advanceOffset(p, 1, true);
          i--;
        }
      } else {
        if (indent >= CODE_INDENT) {
          advanceOffset(p, CODE_INDENT, true);
        } else if (p.blank) {
          advanceNextNonspace(p);
        } else {
          return 1;
        }
      }
      return 0;
    }
    case "html_block":
      return p.blank && (container.htmlBlockType === 6 || container.htmlBlockType === 7)
        ? 1
        : 0;
    case "paragraph":
      return p.blank ? 1 : 0;
    default:
      return 1;
  }
}

/**
 * Run the reference's block-start list in order. Returns:
 *   0 = no match, 1 = matched container (keep going), 2 = matched leaf (stop).
 */
function runBlockStarts(
  p: BlockParser,
  containerRef: { node: BlockNode },
): number {
  const container = containerRef.node;
  // 1. block quote
  if (
    !p.indented &&
    peekChar(p.currentLine, p.nextNonspace) === 62 /* > */
  ) {
    advanceNextNonspace(p);
    advanceOffset(p, 1, false);
    if (isSpaceOrTab(peekChar(p.currentLine, p.offset))) advanceOffset(p, 1, true);
    closeUnmatchedBlocks(p);
    addChild(p, "block_quote", p.nextNonspace);
    containerRef.node = p.tip;
    return 1;
  }
  // 2. ATX heading
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      (match = p.currentLine.slice(p.nextNonspace).match(reATXHeadingMarker))
    ) {
      const marker = match[0];
      advanceNextNonspace(p);
      advanceOffset(p, marker.length, false);
      closeUnmatchedBlocks(p);
      const heading = addChild(p, "heading", p.nextNonspace);
      heading.stringContent = p.currentLine
        .slice(p.offset)
        .replace(/^[ \t]*#+[ \t]*$/, "")
        .replace(/[ \t]+#+[ \t]*$/, "");
      advanceOffset(p, p.currentLine.length - p.offset, false);
      containerRef.node = p.tip;
      return 2;
    }
  }
  // 3. fenced code block
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      (match = p.currentLine.slice(p.nextNonspace).match(reCodeFence))
    ) {
      const fenceLength = match[0].length;
      closeUnmatchedBlocks(p);
      const code = addChild(p, "code_block", p.nextNonspace);
      code.isFenced = true;
      code.fenceLength = fenceLength;
      code.fenceChar = match[0][0] ?? "";
      code.fenceOffset = p.indent;
      advanceNextNonspace(p);
      advanceOffset(p, fenceLength, false);
      containerRef.node = p.tip;
      return 2;
    }
  }
  // 4. HTML block
  if (!p.indented && peekChar(p.currentLine, p.nextNonspace) === 60 /* < */) {
    const s = p.currentLine.slice(p.nextNonspace);
    for (let blockType = 1; blockType <= 7; blockType++) {
      const open = reHtmlBlockOpen[blockType];
      const matched = open !== null && open.test(s);
      if (
        matched &&
        (blockType < 7 ||
          (container.type !== "paragraph" &&
            !(!p.allClosed && !p.blank && p.tip.type === "paragraph")))
      ) {
        closeUnmatchedBlocks(p);
        const b = addChild(p, "html_block", p.offset);
        b.htmlBlockType = blockType;
        containerRef.node = p.tip;
        return 2;
      }
    }
  }
  // 5. setext heading
  {
    let match: RegExpMatchArray | null;
    if (
      !p.indented &&
      container.type === "paragraph" &&
      (match = p.currentLine.slice(p.nextNonspace).match(reSetextHeadingLine))
    ) {
      closeUnmatchedBlocks(p);
      // Strip leading reference definitions from the paragraph before deciding
      // whether any heading TEXT remains (reference: a paragraph that is only
      // reference definitions does NOT become a setext heading).
      container.stringContent = stripReferenceDefinitions(container.stringContent ?? "");
      if ((container.stringContent ?? "").length > 0) {
        const heading = makeBlock("heading", [
          container.sourcepos[0],
          container.sourcepos[1],
        ]);
        heading.stringContent = container.stringContent;
        insertAfter(container, heading);
        unlinkBlock(container);
        p.tip = heading;
        advanceOffset(p, p.currentLine.length - p.offset, false);
        containerRef.node = p.tip;
        return 2;
      }
      // REV66-P1: the paragraph was EMPTIED by reference-definition stripping,
      // so no setext heading is produced. That is NOT "no block start matched" -
      // the reference parser simply moves on to the REMAINING block-start rules,
      // and this line may still open a thematic break (or a list item, etc.).
      // Returning 0 here made the caller append the line to the paragraph and
      // stop, so `[a]: /x` + `---` + STATUS kept a paragraph spanning all three
      // lines and misread the declaration as DEAD. Fall through instead; the
      // paragraph has already been emptied, so nothing is left to continue.
    }
  }
  // 6. thematic break
  if (!p.indented && reThematicBreak.test(p.currentLine.slice(p.nextNonspace))) {
    closeUnmatchedBlocks(p);
    addChild(p, "thematic_break", p.nextNonspace);
    advanceOffset(p, p.currentLine.length - p.offset, false);
    containerRef.node = p.tip;
    return 2;
  }
  // 7. list item
  {
    let data: BlockNode["listData"] | null;
    if (
      (!p.indented || container.type === "list") &&
      (data = parseListMarker(p, container))
    ) {
      closeUnmatchedBlocks(p);
      if (p.tip.type !== "list" || !listsMatch(container.listData, data)) {
        const list = addChild(p, "list", p.nextNonspace);
        list.listData = data;
        containerRef.node = list;
      }
      const item = addChild(p, "item", p.nextNonspace);
      item.listData = data;
      containerRef.node = p.tip;
      return 1;
    }
  }
  // 8. indented code block
  if (p.indented && p.tip.type !== "paragraph" && !p.blank) {
    advanceOffset(p, CODE_INDENT, true);
    closeUnmatchedBlocks(p);
    addChild(p, "code_block", p.offset);
    containerRef.node = p.tip;
    return 2;
  }
  return 0;
}

/** Reference `incorporateLine`, with per-line ownership recorded by the caller. */
function incorporateLine(p: BlockParser, ln: string): void {
  let allMatched = true;
  let container = p.doc;
  p.oldtip = p.tip;
  p.offset = 0;
  p.column = 0;
  p.blank = false;
  p.partiallyConsumedTab = false;
  p.lineNumber += 1;
  if (ln.indexOf("\u0000") !== -1) ln = ln.replace(/\0/g, "\uFFFD");
  p.currentLine = ln;

  // 1. Re-enter open containers from the document downward. Stop at the FIRST
  //    failure; the caller preserves the last matched block.
  let lastChild: BlockNode | null;
  while ((lastChild = container.lastChild) && lastChild.open) {
    container = lastChild;
    findNextNonspace(p);
    const res = continueBlock(p, container);
    if (res === 2) return; // line consumed (a fence closer closed its block)
    if (res === 1) {
      allMatched = false;
    }
    if (!allMatched) {
      container = container.parent ?? p.doc;
      break;
    }
  }

  p.allClosed = container === p.oldtip;
  p.lastMatchedContainer = container;

  let matchedLeaf = container.type !== "paragraph" && acceptsLines(container.type);
  // 2. Offer the surviving level block starts, in the reference order.
  const containerRef = { node: container };
  while (!matchedLeaf) {
    findNextNonspace(p);
    if (!p.indented && !reMaybeSpecial.test(ln.slice(p.nextNonspace))) {
      advanceNextNonspace(p);
      break;
    }
    const res = runBlockStarts(p, containerRef);
    if (res === 1) {
      container = containerRef.node;
      continue;
    } else if (res === 2) {
      container = containerRef.node;
      matchedLeaf = true;
      break;
    } else {
      advanceNextNonspace(p);
      break;
    }
  }

  // 3. Append the remaining text to the appropriate container.
  if (!p.allClosed && !p.blank && p.tip.type === "paragraph") {
    // lazy paragraph continuation
    addLine(p);
  } else {
    closeUnmatchedBlocks(p);
    const t = container.type;
    if (acceptsLines(t)) {
      addLine(p);
      if (
        t === "html_block" &&
        container.htmlBlockType >= 1 &&
        container.htmlBlockType <= 5
      ) {
        const close = reHtmlBlockClose[container.htmlBlockType];
        if (close !== null && close.test(p.currentLine.slice(p.offset))) {
          p.lastLineLength = ln.length;
          finalizeBlock(p, container, p.lineNumber);
        }
      }
    } else if (p.offset < ln.length && !p.blank) {
      container = addChild(p, "paragraph", p.offset);
      p.trace.paragraphStarted[p.lineNumber - 1] = true;
      advanceNextNonspace(p);
      addLine(p);
    }
  }
  p.lastLineLength = ln.length;
}

/**
 * The block tree a line belongs to, plus the two ownership facts consumers read.
 *
 * `changes` / `inside` describe fence membership (an opener line is not
 * "inside"; a closer line is not either — the region strictly between them is).
 *
 * `topLevel` is the STRUCTURAL ownership fact (ENGINE REQUIREMENT 6): true when
 * the line's innermost containing block is a PARAGRAPH whose parent is the
 * document. It is read off the FINALIZED tree, so a paragraph that a reference
 * definition emptied (and the parser unlinked) owns nothing.
 *
 * `paragraphStart` is the PARAGRAPH-START fact: true when the line is the first
 * content line the parser appended to a paragraph. It is recorded DURING the
 * parse (before reference definitions are retroactively stripped), which is what
 * keeps `[a]: /x` + `STATUS:DONE` on ONE paragraph: the declaration did not begin
 * the paragraph, so it is not a declaration. This is the whole of the "a status
 * line directly beneath prose does not declare" policy, kept as a DISTINCT,
 * documented predicate rather than by falsifying the block structure.
 */
export type LineStructure = {
  /** Fence-state CHANGES keyed by line index (true opens, false closes). */
  changes: Map<number, boolean>;
  /** True when a line sits strictly inside an open fenced region. */
  inside: boolean[];
  /** True when a line's innermost block is a document-level paragraph. */
  topLevel: boolean[];
  /** True when a line is the first content line of its paragraph. */
  paragraphStart: boolean[];
};

/** The deepest block whose source span covers `line` (1-based), or null. */
function innermostBlockAtLine(root: BlockNode, line: number): BlockNode | null {
  let best: BlockNode | null = null;
  let bestDepth = -1;
  walkBlocks(root, (node, entering) => {
    if (!entering) return;
    const startLine = node.sourcepos[0][0];
    const endLine = node.sourcepos[1][0];
    if (startLine <= line && line <= endLine) {
      let depth = 0;
      for (let n: BlockNode | null = node; n !== null; n = n.parent) depth += 1;
      if (depth > bestDepth) {
        bestDepth = depth;
        best = node;
      }
    }
  });
  return best;
}

/**
 * Derive the per-line structure from ONE transcription of the reference block
 * parser. Every consumer reads this single result, so the container model cannot
 * be implemented twice and drift again.
 */
export function lineStructure(text: string): LineStructure {
  const normalized = text.replace(/\r\n?/g, "\n");
  const p = makeParser();
  const lines = normalized.split(reLineEnding);
  let len = lines.length;
  if (normalized.charCodeAt(normalized.length - 1) === 10 /* \n */) len -= 1;
  for (let i = 0; i < len; i++) incorporateLine(p, lines[i]);
  let closing: BlockNode | null = p.tip;
  while (closing !== null) {
    const above: BlockNode | null = closing.parent;
    finalizeBlock(p, closing, len);
    closing = above;
  }
  const doc = p.doc;

  const inside = new Array<boolean>(lines.length).fill(false);
  const topLevel = new Array<boolean>(lines.length).fill(false);
  const paragraphStart = new Array<boolean>(lines.length).fill(false);
  const changes = new Map<number, boolean>();

  // Fence membership from each fenced block's CONTENT range. An opener line is
  // NOT inside; the line ENDING the region (an explicit closer, or the first
  // line after a container-held fence ends) is NOT inside either — the region
  // strictly between them is. `changes` records the opener (true) and the
  // explicit closer (false) for any consumer that reads it.
  for (const fence of p.trace.fences) {
    changes.set(fence.open - 1, true);
    if (fence.closerLine !== null) changes.set(fence.closerLine - 1, false);
    for (let lineNo = fence.open + 1; lineNo <= fence.end; lineNo += 1) {
      if (lineNo - 1 < inside.length) inside[lineNo - 1] = true;
    }
  }

  // Structural ownership from the FINALIZED tree, plus the parse-time
  // paragraph-start fact.
  for (let index = 0; index < lines.length; index += 1) {
    paragraphStart[index] = p.trace.paragraphStarted[index] === true;
    const block = innermostBlockAtLine(doc, index + 1);
    topLevel[index] =
      block !== null && block.type === "paragraph" && block.parent !== null &&
      block.parent.type === "document";
  }

  return { changes, inside, topLevel, paragraphStart };
}
