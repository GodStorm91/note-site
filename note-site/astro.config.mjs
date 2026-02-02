import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';

export default defineConfig({
  integrations: [mdx()],
  srcDir: 'src',
  site: 'https://example.com', // đổi thành domain thật sau
});
