import { Article, DeepDive, ShortForm } from './types';

export const CURRENT_FLOW: Article[] = [
  {
    id: '1',
    type: 'Essay',
    title: 'The Architecture of Global Connectivity in the Post-Fiber Era',
    excerpt: "An examination of how physical submarine cables dictate digital sovereignty and reshape geopolitical boundaries beneath the ocean's surface.",
    author: 'Dr. Aris Thorne',
    readTime: '14 min read',
    image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCjDQW8qTzVwJC1OPHj9ptu-PFTE6_Xfg8lMQydKdGr4mroWqYeED_d3lOBMHGmjMLJGGdohiEa1FKKNiTN62sjj5HfXoNyIk0ht4eVsqxTXxvk5DO2IPR2qwFH469cEbd3u3D8SUcBn8NTRGW_0cIlTktHVreE-z41asLsf0HdiAoQ2JYtY3e5AsiWc-zHPrNd7WZyp1Kx9v6RxAPpCXeE_nLfebSbW16Bu8cNbztPWLs7kSCq4VDKfwPQzJjPDII2ATT6va-Un0wU'
  },
  {
    id: '2',
    type: 'Analysis',
    title: 'Fluid Dynamics of Information Markets',
    excerpt: 'How attention flows mirror physical phenomena, and why traditional economic models fail to capture the velocity of modern sentiment cascades.',
    author: 'Elena Rostova',
    readTime: '22 min read',
    image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBCny4ZltE9dgtP000J2fW3KTgbwDhqfP7DZJGaA0ZnyCbEvUMhAoSxcof3Gx4S3TkG0R5WkU4HUkm9d5SBR5GERgpFl92EUFXteq5OYzRnnrjBg6nHgPn-twOuxEmHgJXQA2qWk0NQTDgoSMOtw2ndxrorwGHuLpJknTUP2y0cScx6xTZi50nrb_NQewHKz4OgDSPsk12e6P9cKzKE8pVq_145s0CbjYsb9ZZ3IulXiVhiSmqv71U0AEhr2G3MRL3XSAIl8OFAmCbd'
  },
  {
    id: '3',
    type: 'Quote',
    title: 'Mapping the Unseen Order',
    excerpt: 'A structuralist approach to digital archives and the preservation of ephemeral discourse.',
    author: 'Institute for Digital Heritage',
    quote: '"The stream is not chaos; it is a higher-order structure we have yet to map."'
  },
  {
    id: '4',
    type: 'Video',
    title: 'The Digital Archaeology of 8-bit Landscapes',
    excerpt: 'A visual exploration of how early computing constraints birthed a permanent aesthetic language in modern design.',
    author: 'Soren K. Müller',
    readTime: '18 min watch',
    image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCCr6Ne0nX1dtcRZ1czSdTqBmH1Jau9nYBFa5qb0L4hB75ljE5R8WrKLW0Xa5r2N8nMfeu-RLV6zSvUkbPRX_g0kQqvgTXVbKervh_IcxGtiLb2Ei6Q57DF7n3fVGA7rHG8lZyGeTV6WvmG5shremUbK5ywYbMIL6bL1GlCfPqfaqwu3cI8Svnp4EAwGqV6bDdJ36ntxOwKyDKGc0tNqDBY9Yg-gPyKakX4Bc7hqGsELhrTwUIHNOvVlNrz40AdmueJk-7tXdNrxb3N'
  },
  {
    id: '5',
    type: 'Visual Essay',
    title: 'Brutalist Botany: The Greening of Concrete Heavens',
    excerpt: 'Documenting the intersection of harsh modernist architecture and the resilient return of urban flora.',
    author: 'Maya Lin-Soto',
    readTime: '12 min read',
    image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuD4_9cvzFfq3N-ujkXhM0uT4sXbN4xXHN3HHN8FRZMakQwtIZCA9NQeRZJfNZNO2e0CSC3bwKkEcq9tkTB7-WZ5sUpQHCEKvoV-0JqCB0O3WwDIUGxuEyXNfMx2wMcbQcEJISE6lqZ_OfdV2WqGvzar3C2aQNiWMjlvqJbRh9IuOwUfhSLcFeL5noXcCjaUJloFhRq_oOJxaiR2vkUT2CJ7uMmUTs-rVxgYwTybCHrgpmK66nqmqkG4Z2zEJSkCMBoOouiSJgy4DGuz'
  },
  {
    id: '6',
    type: 'Video',
    title: 'The Last Signals from the Voyager Horizon',
    excerpt: 'A cinematic journey through the final data transmissions from our furthest physical reach into the cosmos.',
    author: 'The Spatium Lab',
    readTime: '25 min watch',
    image: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBfA-5fixLlgqBhOmsh2ms_oYl0XPh4koDGSEYevZTj_wQNoKHtlz0-aSDADxkXArEojXdiDHHSssDGjwIV3Xwpw9FHrV76IUvE8zV_5vfSyM9Dk7JwaMRat_xf9Zm8rD_abBWnEIZCy39S32uU0J5rON7cYYfgE-Co5e9QVi95QqryPFue2pi2iAWWfYqkdtk3GUvywN_W8A-f7rwcxAtgNF3HaVTxEieVO8wsLqNUiOhT09cbMSR3MXPZ91jkS8-MvcyA5777OF8E'
  }
];

export const DEEP_DIVES: DeepDive[] = [
  {
    id: '1',
    label: 'Long-form Transcript',
    title: 'The Urbanism of Silence',
    description: 'As megacities grow denser, urban planners are beginning to treat acoustic environments as critical infrastructure. A conversation with soundscape ecologists on engineering quiet amidst the concrete.',
    footerLabel: 'Includes embedded audio · 45 min read',
    type: 'transcript'
  },
  {
    id: '2',
    label: 'Historical Archives',
    title: 'Letters from the First Technocrats',
    description: 'Newly digitized correspondence reveals the philosophical anxieties of mid-20th century cyberneticists as they built the foundations of the modern algorithmic state.',
    footerLabel: '12 Primary Documents · Annotated',
    type: 'archive'
  }
];

export const SHORT_FORM: ShortForm[] = [
  {
    id: '1',
    author: 'Dr. Silas Vance',
    handle: '@svance_theory',
    avatar: 'https://lh3.googleusercontent.com/aida-public/AB6AXuAutCS5n4x8bOQUQNZ7yqBbfLeg3mxdY3ED7XVEC4s9g3Q94ZM6yIMJTgdKtK9ckgAcpVummL7HDfv472C6lHaIwC7WDTZ4SSfNNyWEZ-LeLz8v95NUaKvV4V8jgj8I1sTb4o285rfVr3XuTIm0RRP56nmufrPhzMpcNiKIfh7mQE1X0Xm9c3viQpbFHOt6KufhlEnmzYkFZRG54zY3CkwyCi6UatJaJsGkuFbdlS2bD0vFvVKOap0JZwCy3o3t2uzrDuai8lIBG4Vy',
    content: '"The irony of the post-scarcity information age is that our attention has become the only finite resource. We are drowning in signals while starved for synthesis."',
    time: '2 hours ago',
    topic: 'Information Theory'
  },
  {
    id: '2',
    author: 'Elena Rostova',
    handle: '@rostova_e',
    avatar: 'https://lh3.googleusercontent.com/aida-public/AB6AXuCYrVRlpTQfO2TyNq3_Hugv_jsposMWZVr8-BWuPNIJI65njeJ5hhB-oNoOAcA3SIY64IhwK70G-SMKUBVxVLYLK0Q6TJS_A7ZoYBxQa5rKAZ9MtAgva2rXnc355kPMtRcgsfSdu0Hvz4rIM3NVTno_EOrSPHfWhcROWHmbBT9y7Xemf5ddrvazra8slBZ75aRIuy6e523COmb55n0Bh7b8jgq3HKHGwJHFu4VdzwpLV9ONPha5BicixWQJ_oAg2N4DW8pUfkploAwR',
    content: "Mapping out the new urbanism patterns in coastal megacities. The data from last week's sensors shows a fascinating migration away from the central hubs during peak sunlight hours. #ClimateAdaptation",
    time: '5 hours ago',
    topic: 'Urbanism',
    isSpecial: true
  },
  {
    id: '3',
    author: 'Meta-Research Collective',
    handle: '@metaresearch',
    avatar: '', // Initial fallback to letter avatar
    content: 'Thread 🧵: Why the current geopolitical consensus on AI regulation fundamentally misunderstands the open-source community dynamics.',
    time: '1 day ago',
    topic: 'Geopolitics'
  },
  {
    id: '4',
    author: "Kaelen O'Connor",
    handle: '@kaelen_o',
    avatar: 'https://lh3.googleusercontent.com/aida-public/AB6AXuBViRajIJZpD6XiQJI3YcFHpjyc3XRxVWlYvQ-zFLlVIHja-HKXe7nBJaoa6Tbmb2KvK3Cr1md41ZvW63fOHipYOkmZ_S1rBmwgBUm3Aq2moEiEWHJTU9iOHmVbQrKIRMNG3s6yFe03Ht2CyESxrZIKXuknvXzzRPI57srDHLVVEwj3AtzUl5gAbKjZ6nN4EcZOYzWQPpxqrdtARjgHBbPxlLQo4zZrhFLejZCCAaSSgbf29lL4oQ7a6feFfMhCF85naf4a6Wwv0zx9',
    content: "Just published the updated transcripts from the 1970s cybernetics symposium. The parallels to today's LLM discourse are staggering. History doesn't repeat, but it definitely rhymes.",
    time: '2 days ago',
    topic: 'Archival'
  }
];
