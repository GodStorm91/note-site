import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

export default defineConfig({
  integrations: [mdx()],
  srcDir: 'src',
  site: 'https://n.khanh.page',
  build: {
    inlineStylesheets: 'always',
  },
});
