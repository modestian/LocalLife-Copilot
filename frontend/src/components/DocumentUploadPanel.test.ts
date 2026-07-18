import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { documentApi } from '@/api/documents'
import { ApiClientError } from '@/api/errors'
import type { AcceptedTask } from '@/types/document'

import DocumentUploadPanel from './DocumentUploadPanel.vue'

vi.mock('@/api/documents', () => ({
  documentApi: { upload: vi.fn() },
}))

const accepted: AcceptedTask = {
  task_id: 'task-upload-1',
  status: 'PENDING',
  progress: 0,
  status_url: '/api/v1/tasks/task-upload-1',
}

function mountPanel(disabled = false) {
  return mount(DocumentUploadPanel, {
    props: {
      knowledgeBaseId: 'kb-1',
      defaultChunkSize: 500,
      defaultChunkOverlap: 80,
      disabled,
    },
  })
}

async function selectFiles(
  wrapper: ReturnType<typeof mountPanel>,
  files: File[],
): Promise<void> {
  const input = wrapper.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
}

describe('DocumentUploadPanel', () => {
  beforeEach(() => {
    vi.mocked(documentApi.upload).mockReset().mockResolvedValue(accepted)
  })

  it('submits validated files and documented upload options as one batch', async () => {
    const wrapper = mountPanel()
    const files = [
      new File(['markdown'], 'guide.md', { type: 'text/markdown' }),
      new File(['name,price'], 'shops.csv', { type: 'text/csv' }),
    ]
    await selectFiles(wrapper, files)

    await wrapper.get('.upload-options select').setValue('semantic')
    const numberInputs = wrapper.findAll('.upload-options input[type="number"]')
    await numberInputs[0]?.setValue(800)
    await numberInputs[1]?.setValue(120)
    await wrapper.get('.upload-options input[placeholder="使用知识库默认方案"]').setValue('clean-v2')
    await wrapper.get('.checkbox-option input').setValue(true)

    expect(wrapper.text()).toContain('待上传 2 个')
    expect(wrapper.text()).toContain('全部通过预检')
    await wrapper.get('.upload-actions button').trigger('click')
    await flushPromises()

    expect(documentApi.upload).toHaveBeenCalledWith('kb-1', {
      files,
      splitter: 'semantic',
      chunk_size: 800,
      chunk_overlap: 120,
      cleaning_profile_id: 'clean-v2',
      force_new_version: true,
    })
    expect(wrapper.emitted('accepted')?.[0]?.[0]).toEqual(accepted)
    expect((wrapper.emitted('accepted')?.[0]?.[1] as File[]).map((file) => file.name)).toEqual([
      'guide.md',
      'shops.csv',
    ])
    expect(wrapper.find('.selected-files').exists()).toBe(false)
  })

  it('blocks unsupported and MIME-mismatched files before calling the API', async () => {
    const wrapper = mountPanel()
    await selectFiles(wrapper, [
      new File(['payload'], 'script.exe', { type: 'application/octet-stream' }),
      new File(['not a pdf'], 'menu.pdf', { type: 'text/plain' }),
    ])

    expect(wrapper.text()).toContain('2 个未通过校验')
    expect(wrapper.text()).toContain('不支持 .exe 格式')
    expect(wrapper.text()).toContain('MIME text/plain 与文件格式不匹配')
    expect(wrapper.get('.upload-actions button').attributes('disabled')).toBeDefined()
    expect(documentApi.upload).not.toHaveBeenCalled()
  })

  it('keeps the selected files and shows the server error when upload is rejected', async () => {
    vi.mocked(documentApi.upload).mockRejectedValue(new ApiClientError({
      status: 422,
      code: 'UPLOAD_CONTENT_INVALID',
      message: '文件内容与声明格式不一致',
    }))
    const wrapper = mountPanel()
    await selectFiles(wrapper, [
      new File(['markdown'], 'guide.md', { type: 'text/markdown' }),
    ])

    await wrapper.get('.upload-actions button').trigger('click')
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('文件内容与声明格式不一致')
    expect(wrapper.text()).toContain('guide.md')
    expect(wrapper.emitted('accepted')).toBeUndefined()
  })

  it('disables file selection and submission without management permission', () => {
    const wrapper = mountPanel(true)

    expect(wrapper.get('.drop-zone').attributes('disabled')).toBeDefined()
    expect(wrapper.get('input[type="file"]').attributes('disabled')).toBeDefined()
    expect(wrapper.get('.upload-actions button').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('当前账号不可上传文档')
  })
})
