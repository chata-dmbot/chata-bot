export const NavigationOverlay = () => {
  return (
    <div
      role="lineContainer"
      className="fixed items-center box-border caret-transparent flex h-[1000px] justify-center w-full z-50 left-0 top-0"
    >
      <div className="absolute bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50 left-0 top-[420px] md:top-[340px]"></div>
      <div className="absolute bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50 right-0 top-[420px] md:top-[340px]"></div>
      <div className="absolute items-center box-border caret-transparent flex justify-center w-full bottom-[420px] md:bottom-[340px]">
        <div className="box-border caret-transparent w-full">
          <div className="relative bg-white box-border caret-transparent h-px opacity-30 w-0 z-50"></div>
        </div>
        <div className="relative box-border caret-transparent flex shrink-0 justify-between max-w-[1000px] w-full">
          <div className="relative bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50"></div>
          <div className="relative bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50"></div>
        </div>
        <div className="box-border caret-transparent flex justify-end w-full">
          <div className="relative bg-white box-border caret-transparent h-px opacity-30 w-0 z-50"></div>
        </div>
      </div>
      <div className="absolute items-center bg-red-50 box-border caret-transparent flex justify-center top-[180px]">
        <div className="absolute bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50 left-0"></div>
        <div className="absolute bg-white box-border caret-transparent h-px opacity-30 w-[400px] z-50 right-0"></div>
      </div>
      <div className="absolute items-center box-border caret-transparent flex flex-col h-[420px] justify-center w-full z-[60] pb-2.5 px-2.5 left-0 bottom-0 md:h-[340px] md:pb-5">
        <div className="relative bg-white box-border caret-transparent h-px opacity-30 origin-[400px_0.5px] w-screen z-50 left-0"></div>
        <div className="relative items-center bg-transparent box-border caret-transparent flex h-[54px] justify-center max-w-[1000px] origin-[390px_27px] w-full overflow-hidden hover:bg-white/30">
          <div className="box-border caret-transparent h-auto w-full left-0 bottom-0 md:h-[60px]"></div>
          <div className="absolute box-border caret-transparent h-[59px] max-w-[1000px] opacity-[0.1293] w-full px-2.5 -top-0.5 md:opacity-[0.469] md:px-0">
            <div className="relative bg-[radial-gradient(at_center_bottom,rgb(255,255,255)_0px,rgba(0,0,0,0)_70%)] box-border caret-transparent h-full w-full"></div>
          </div>
          <div className="absolute text-base font-normal box-border caret-transparent leading-6 md:text-xl md:leading-7">
            SCROLL
          </div>
        </div>
        <div className="relative bg-white box-border caret-transparent h-px opacity-30 origin-[400px_0.5px] w-screen z-50 left-0"></div>
      </div>
      <div className="fixed text-black text-sm items-center box-border caret-transparent flex flex-col h-[1000px] justify-center leading-5 w-full z-[999] left-0 top-px">
        <div className="relative box-border caret-transparent flex flex-col h-full w-full px-2.5 py-3 md:px-5 md:py-[22px]">
          <div className="relative box-border caret-transparent flex basis-[0%] grow w-full">
            <div className="relative box-border caret-transparent grow">
              <div className="bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mr-px -mt-0.5 right-0 top-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mr-px -mb-px right-0 bottom-0"></div>
            </div>
            <div className="box-border caret-transparent grow max-w-[1000px] w-full"></div>
            <div className="relative box-border caret-transparent grow">
              <div className="bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5 right-0 top-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px right-0 bottom-0"></div>
            </div>
            <div className="absolute items-center box-border caret-transparent flex h-full justify-center w-full left-0 top-0">
              <div className="relative box-border caret-transparent h-full max-w-[2052px] w-full">
                <div className="bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5 right-0 top-0"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px right-0 bottom-0"></div>
              </div>
            </div>
          </div>
          <div className="box-border caret-transparent flex h-40 w-full md:h-[322px]">
            <div className="box-border caret-transparent grow"></div>
            <div className="box-border caret-transparent grow max-w-[1000px] w-full"></div>
            <div className="box-border caret-transparent grow"></div>
          </div>
          <div className="relative box-border caret-transparent flex basis-[0%] grow w-full">
            <div className="relative box-border caret-transparent grow">
              <div className="bg-white box-border caret-transparent h-px w-px z-50 -mt-px"></div>
              <div className="absolute bg-white box-border caret-transparent h-px mt-[-3px] w-px z-50 -mr-px right-0 top-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px right-0 bottom-0"></div>
            </div>
            <div className="relative box-border caret-transparent grow h-full max-w-[1000px] w-full">
              <div className="relative box-border caret-transparent flex flex-col h-full">
                <div className="box-border caret-transparent grow"></div>
                <div className="items-center box-border caret-transparent flex shrink-0 h-[50px] justify-center md:h-[60px]"></div>
                <div className="box-border caret-transparent grow"></div>
              </div>
            </div>
            <div className="relative box-border caret-transparent grow">
              <div className="bg-white box-border caret-transparent h-px mt-[-3px] w-px z-50"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5 right-0 top-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
              <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px right-0 bottom-0"></div>
            </div>
            <div className="absolute items-center box-border caret-transparent flex h-full justify-center w-full left-0 top-0">
              <div className="relative box-border caret-transparent h-full max-w-[2052px] w-full">
                <div className="bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mt-0.5 right-0 top-0"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px left-0 bottom-0"></div>
                <div className="absolute bg-white box-border caret-transparent h-px w-px z-50 -mb-px right-0 bottom-0"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div className="items-center box-border caret-transparent flex flex-col h-full w-full p-0 md:p-5">
        <div className="absolute box-border caret-transparent flex h-[420px] max-w-[1000px] w-full py-2.5 bottom-auto md:h-[338px] md:pt-0 md:pb-5 md:bottom-0">
          <div className="absolute box-border caret-transparent origin-[65.8984px_31px] w-[132px] overflow-hidden mt-0 left-2.5 top-auto md:-mt-0.5 md:left-0 md:top-0">
            <div className="text-black text-xs font-normal bg-white box-border caret-transparent flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5">
              <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
                TOTAL EDITIONS
              </div>
            </div>
            <div className="text-3xl box-border caret-transparent h-[30px] tracking-[-1.5px] leading-9 mt-[-3px] ml-0 md:text-5xl md:h-[45px] md:tracking-[-2.4px] md:leading-[48px] md:-ml-1">
              18.632
            </div>
          </div>
          <div className="absolute items-end box-border caret-transparent flex flex-col origin-[41.3281px_31px] w-[83px] overflow-hidden mt-0 right-2.5 md:-mt-0.5 md:right-0">
            <div className="text-black text-xs font-normal bg-white box-border caret-transparent flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5">
              <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
                TOTAL NFTS
              </div>
            </div>
            <div className="text-3xl box-border caret-transparent h-[30px] tracking-[-1.5px] leading-9 mt-[-3px] md:text-5xl md:h-[45px] md:tracking-[-2.4px] md:leading-[48px]">
              95
            </div>
          </div>
          <div className="absolute box-border caret-transparent origin-[62.1797px_31.5px] w-[124px] overflow-hidden left-2.5 bottom-0 md:left-0 md:bottom-[150px]">
            <div className="text-3xl box-border caret-transparent h-[30px] tracking-[-1.5px] leading-9 ml-0 mb-0 md:text-5xl md:h-[45px] md:tracking-[-2.4px] md:leading-[48px] md:mb-[-5px] md:-ml-1">
              2020
            </div>
            <div className="text-black text-xs font-normal bg-white box-border caret-transparent flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit mb-0 px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5 md:mb-[3px]">
              <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
                FIRST NFT MINTED
              </div>
            </div>
          </div>
          <div className="absolute items-end box-border caret-transparent flex flex-col origin-[64.3672px_31.5px] w-[129px] overflow-hidden right-2.5 bottom-0 md:right-0 md:bottom-[150px]">
            <div className="text-3xl box-border caret-transparent h-[30px] tracking-[-1.5px] leading-9 mb-0 md:text-5xl md:h-[45px] md:tracking-[-2.4px] md:leading-[48px] md:mb-[-5px]">
              13
            </div>
            <div className="text-black text-xs font-normal bg-white box-border caret-transparent flex h-fit tracking-[-0.3px] leading-4 text-nowrap w-fit mb-0 px-[5px] md:text-sm md:tracking-[-0.35px] md:leading-5 md:mb-[3px]">
              <div className="text-xs box-border caret-transparent tracking-[-0.3px] leading-4 text-nowrap md:text-sm md:tracking-[-0.35px] md:leading-5">
                UNIQUE PARTNERS
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
