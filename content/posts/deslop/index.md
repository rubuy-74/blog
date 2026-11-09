---
title: "deslop"
date: 2026-11-06
---

**TLDR**; Created a web extension for classifying AI generated content on short form video platforms. Struggled with visual identity choices and the actual usability of the project, not moving on with this one

<div class="image-row"><img src="images/img/Pasted%20image%2020261106230004.png" alt="Pasted image 20261106230004" loading="lazy" decoding="async"></div>


project link: https://github.com/rubuy-74/deslop

I saw the annoucement of Jev on twitter a few weeks (months ago now probably) and I really thought it was going to change a lot of things, apparently I was being too optmistic (prove me wrong).

So I wanted to experiment what it could do and check its limitations, so I thought for a little while and it came up to me: I watch a lot of short form content, maybe I could have something that shows me that a video is AI generated or not and I can just skip it.

It sounded like a good idea at first and I was excited for the challenge, because at the time there were no image classification, you need to use another model to describe the images with text and then Jev model would ingest that text and actually classify the image.

While I was doing work for uni and my thesis, Cloudflare (my beloved) launched Clef, which is the first model trained by them and its a classification model just like Jev, but there's a thing, it let's you send up to 4 images per request. That was my queue to continue the project.

So, what I did first was to create a decision engine before looking into the characteristics of each one of the short term platforms.

### the decision engine

This is the brains of the operation. The video gets loaded to the engine, it takes screenshots of the first 2 seconds of the video and it sends them to Clef. The engine consumes the response and based on it's confidence level decides if will display the warning overlay or if it just ignores it.

The engine classifies the video into 5 possible categories:
- Organic: real human-made data.
- Absurdist AI: videos with obvious synthetic rendering artifacts.
- Synthetic Parody: deepfakes or AI parodies of famous people (like AI Trump videos).
- Static AI Slideshow: compilations of AI-generated images.
- Other AI: any synthetic content that doesn't fit the previous buckets.

For those who care about this sort of stuff, here it is the clef config:
```json
export const CLEF_CONFIG = {
  model: 'clef-flash',
  threshold: 0.80,
  state:
    'Three chronological frames sampled near the start ' +
    'of a short-form mobile video. Judge the visual content.',
  questions: {
    slop_category: {
      type: 'choice',
      instructions:
        'Which category best describes this video? Judge by visual signatures, not topic.',
      criteria: {
        organic:
          'Real camera footage, human-made animation, gameplay, or standard creator content with natural optics and motion',
        absurdist_ai:
          'Synthetic rendering artifacts (plastic textures, impossible physics or speculars, distorted micro-details); e.g. anthropomorphic objects or foods acting out dramas',
        synthetic_parody:
          'Real public-figure faces mapped onto incongruous bodies; facial boundary artifacts, frozen gaze, ear/jaw blending between frames',
        static_ai_slideshow:
          'Sequence of static generative illustrations with no organic camera motion and oversized automated captions',
        other_ai:
          'AI-generated or synthetic content not matching the other categories: smeared or hallucinated detail, generative artifacts of any kind',
      },
    },
    is_slop: {
      type: 'noul',
      instructions: 'Is this video AI-generated slop or low-effort synthetic content?',
      criteria: {
        true: 'Any synthetic generation, face-swap, or automated slideshow content',
        false: 'Genuinely filmed or human-crafted content, even if filtered or edited',
      },
    },
    visual_authenticity: {
      type: 'score',
      instructions: 'Rate the organic visual authenticity of this media.',
      criteria: [
        'Pure synthetic generation: plastic skin, uncanny blending, hallucinated limbs',
        'Heavy AI augmentation with obvious visual artifacts',
        'Ambiguous or heavily filtered authentic footage',
        'Verifiable organic photography with consistent real-world optics',
      ],
    },
  },
};
```

For testing if the model actual gave some good results, I created a testing suite. I downloaded 20 videos (4 of each category) and classified them manually then ran the model against them. Since the results were somewhat satisfactory, I continued.

With the engine working, I could move on to the actual platform integration.

### platform integrations

The extension was built for Youtube Shorts, Tiktok and Instagram Reels in that order. I started with youtube because it was the more leanient one for determining the stop buttons and creating the overlay. Tiktok (and Reels) only work for logged in users and required some workarounds to be get working.

For skipping videos on Tiktok, a KeyboardEvent must be simulated and the video to be overlayed are not really easy to find. 

Instagram was from a far the most difficult one to integrate. I couldn't find a way to pinpoint the video on the DOM to overlay, so the whole screen gets blurred for a flagged video.

### challenges

The biggest challenge from afar was defining the visual identity and pinpointing the actual use-case for this app. I have no problem saying this... I feel like this project wasn't really successful for my standards, but those are the projects that I learn the most from.

This was the first time that I actually tried to define the visual identity, logo and vision for a project solo. I'm no designer and I thought this would be much easier than it was, however it's now a good thing to challenge myself to define those aspects for any new project of mine.

### conclusions

This project teached me a ton about how to actually build something can be eventually a product, how to account for what purpose a project actually have for its users and that designing can be tough when you want to do it right.

It's those things that you don't really get to the final point, but what it really matters is the path and what you learned from it (the friends you made on the way).

If you are also excited about how Jev can change the world around us or just want to talk about short form videos and how they affect us, you can shoot me a message to twitter, linkedin and email.

twitter: https://x.com/rubuy_74 \
linkedin: https://www.linkedin.com/in/rubemneto74/ \
email: rubemviscard2635@gmail.com