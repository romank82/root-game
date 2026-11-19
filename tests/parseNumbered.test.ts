import assert from 'node:assert/strict'
import test from 'node:test'
import {
  mergeParsedFields,
  normalizeBlocks,
  parseNumbered,
} from '../src/utils/missionTranslationParse.ts'

test('разбирает однострочные нумерованные поля', () => {
  assert.deepEqual(
    parseNumbered('[1] The Archive\n[2] Find the artifact\n[3] Scan the code', 3),
    ['The Archive', 'Find the artifact', 'Scan the code'],
  )
})

test('сохраняет многострочное поле', () => {
  assert.deepEqual(
    parseNumbered('[1] Title\n[2] First line\nsecond line\n[3] Last', 3),
    ['Title', 'First line\nsecond line', 'Last'],
  )
})

test('сохраняет пустую строку внутри многострочного поля', () => {
  assert.deepEqual(
    parseNumbered('[1] Title\n[2] First line\n\nthird line\n[3] Last', 3),
    ['Title', 'First line\n\nthird line', 'Last'],
  )
})

test('игнорирует текст до первого нумерованного поля', () => {
  assert.deepEqual(
    parseNumbered('вводная строка\n\n[1] Title\n[2] Description', 3),
    ['Title', 'Description', ''],
  )
})

test('возвращает пустые поля, если нумерации нет', () => {
  assert.deepEqual(parseNumbered('обычный текст\nещё строка', 2), ['', ''])
})

test('возвращает null для индекса за пределами диапазона', () => {
  assert.equal(parseNumbered('[1] Title\n[4] Invalid', 3), null)
})

test('mergeParsedFields возвращает null для пустого ввода', () => {
  assert.equal(mergeParsedFields({ title: 'Old' }, ['', ''], ['title', 'description']), null)
})

test('mergeParsedFields возвращает null для текста без маркеров', () => {
  assert.equal(
    mergeParsedFields({ title: 'Old' }, parseNumbered('обычный текст', 2) ?? [], ['title', 'description']),
    null,
  )
})

test('mergeParsedFields обновляет только непустое частичное поле', () => {
  assert.deepEqual(
    mergeParsedFields(
      { title: 'Old title', description: 'Keep description' },
      ['A', ''],
      ['title', 'description'],
    ),
    { title: 'A', description: 'Keep description', contentUi: {} },
  )
})

test('mergeParsedFields обновляет все поля полной вставки', () => {
  assert.deepEqual(
    mergeParsedFields(
      { title: 'Old', description: 'Old description', contentUi: { label: 'Old label' } },
      ['New', 'New description', 'New label'],
      ['title', 'description', 'label'],
    ),
    {
      title: 'New',
      description: 'New description',
      contentUi: { label: 'New label' },
    },
  )
})

test('mergeParsedFields обрезает пробелы по краям значений', () => {
  assert.deepEqual(
    mergeParsedFields({}, ['  Title  ', '  Description  '], ['title', 'description']),
    { title: 'Title', description: 'Description', contentUi: {} },
  )
})

test('mergeParsedFields сохраняет существующий contentUi.label', () => {
  assert.deepEqual(
    mergeParsedFields(
      { title: 'Old', contentUi: { label: 'Keep label' } },
      ['New title', ''],
      ['title', 'description'],
    ),
    { title: 'New title', contentUi: { label: 'Keep label' } },
  )
})

test('normalizeBlocks возвращает валидный массив строк', () => {
  assert.deepEqual(normalizeBlocks('["one", "two"]'), {
    blocks: ['one', 'two'],
    error: null,
  })
})

test('normalizeBlocks возвращает ошибку для невалидного JSON', () => {
  const result = normalizeBlocks('["one"')
  assert.equal(result.blocks, null)
  assert.equal(typeof result.error, 'string')
  assert.notEqual(result.error, '')
})

test('normalizeBlocks считает пустую строку пустым массивом', () => {
  assert.deepEqual(normalizeBlocks('   '), { blocks: [], error: null })
})

test('normalizeBlocks возвращает ошибку для значения не-массива', () => {
  const result = normalizeBlocks('"one"')
  assert.equal(result.blocks, null)
  assert.equal(typeof result.error, 'string')
})

test('normalizeBlocks возвращает ошибку для нестроковых элементов', () => {
  const result = normalizeBlocks('["one", 2]')
  assert.equal(result.blocks, null)
  assert.equal(typeof result.error, 'string')
})
